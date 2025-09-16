import os
import re
import tempfile
import zipfile
import shutil
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from urllib.parse import urljoin, urlparse
from flask import Blueprint, request, jsonify, send_file
from flask_cors import cross_origin

download_bp = Blueprint('download', __name__)

def sanitize_filename(title):
    """Remove characters that cannot be used in filenames."""
    return re.sub(r'[\\/*?:">>"<>|]', "", title)

def download_qiita_article(url, output_dir="."):
    """Download a Qiita article as Markdown."""
    print(f"Fetching article from: {url}")
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Error fetching article: {e}")

    soup = BeautifulSoup(response.content, 'html.parser')

    # --- Find and sanitize article title ---
    title_tag = soup.find('h1', attrs={'data-logly-title': 'true'})
    if not title_tag:
        # Fallback to the first h1 tag if the specific attribute is not found
        title_tag = soup.find('h1')

    if not title_tag:
        print("Could not find article title. Using a default name.")
        title = "qiita_article"
    else:
        title = title_tag.get_text().strip()

    sanitized_title = sanitize_filename(title)
    
    # --- Create output directory for the article ---
    article_output_dir = os.path.join(output_dir, sanitized_title)
    os.makedirs(article_output_dir, exist_ok=True)
    
    md_filename = os.path.join(article_output_dir, "article.md")
    images_dir = os.path.join(article_output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # --- Find article content ---
    content_div = soup.find('section', class_='it-MdContent')
    if not content_div:
        raise Exception("Could not find article content.")

    # --- Download images and update paths ---
    print("Downloading images...")
    for img_tag in content_div.find_all('img'):
        img_url = img_tag.get('src')
        if not img_url:
            continue

        img_url = urljoin(url, img_url)
        
        try:
            img_response = requests.get(img_url, stream=True)
            img_response.raise_for_status()

            img_name = os.path.basename(urlparse(img_url).path)
            if not img_name:
                img_name = f"image_{hash(img_url)}.jpg" # Assign a name if URL path ends in /

            img_local_path = os.path.join(images_dir, img_name)
            
            with open(img_local_path, 'wb') as f:
                for chunk in img_response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # Update the src to be a relative path for portability
            img_local_relative_path = os.path.join("images", img_name)
            img_tag['src'] = img_local_relative_path
            print(f"  - Downloaded {img_name}")

            # If the image is wrapped in a link, unwrap it to prevent linked markdown image
            if img_tag.parent.name == 'a':
                img_tag.parent.unwrap()

        except requests.exceptions.RequestException as e:
            print(f"  - Failed to download {img_url}: {e}")

    # --- Convert HTML to Markdown ---
    print("Converting to Markdown...")
    # Use the modified HTML string for conversion
    markdown_content = md(str(content_div), heading_style="ATX")

    # --- Save Markdown file ---
    with open(md_filename, 'w', encoding='utf-8') as f:
        f.write(markdown_content)

    print(f"Successfully downloaded article to '{article_output_dir}'")
    return article_output_dir, sanitized_title

@download_bp.route('/download', methods=['POST'])
@cross_origin()
def download_article():
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'error': 'URLが指定されていません'}), 400
        
        url = data['url']
        
        # URLの簡単な検証
        if not url or not isinstance(url, str):
            return jsonify({'error': '有効なURLを入力してください'}), 400
        
        if 'qiita.com' not in url:
            return jsonify({'error': 'QiitaのURLを入力してください'}), 400
        
        # 一時ディレクトリを作成
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # 記事をダウンロード
                article_dir, article_title = download_qiita_article(url, temp_dir)
                
                # ZIPファイルを作成
                zip_filename = f"{article_title}.zip"
                zip_path = os.path.join(temp_dir, zip_filename)
                
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(article_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            # ZIP内でのパスを相対パスにする
                            arcname = os.path.relpath(file_path, temp_dir)
                            zipf.write(file_path, arcname)
                
                # ZIPファイルを送信
                return send_file(
                    zip_path,
                    as_attachment=True,
                    download_name=zip_filename,
                    mimetype='application/zip'
                )
                
            except Exception as e:
                print(f"Download error: {e}")
                return jsonify({'error': f'ダウンロードに失敗しました: {str(e)}'}), 500
                
    except Exception as e:
        print(f"Request error: {e}")
        return jsonify({'error': 'リクエストの処理に失敗しました'}), 500

