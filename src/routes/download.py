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
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"Fetching article from: {url}")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        logger.info(f"Successfully fetched article, status: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch article: {e}")
        raise Exception(f"Error fetching article: {e}")

    soup = BeautifulSoup(response.content, 'html.parser')

    # --- Find and sanitize article title ---
    title_tag = soup.find('h1', attrs={'data-logly-title': 'true'})
    if not title_tag:
        # Fallback to the first h1 tag if the specific attribute is not found
        title_tag = soup.find('h1')

    if not title_tag:
        logger.warning("Could not find article title. Using a default name.")
        title = "qiita_article"
    else:
        title = title_tag.get_text().strip()
        logger.info(f"Found article title: {title}")

    sanitized_title = sanitize_filename(title)
    
    # --- Create output directory for the article ---
    article_output_dir = os.path.join(output_dir, sanitized_title)
    os.makedirs(article_output_dir, exist_ok=True)
    logger.info(f"Created article directory: {article_output_dir}")
    
    md_filename = os.path.join(article_output_dir, "article.md")
    images_dir = os.path.join(article_output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # --- Find article content ---
    content_div = soup.find('section', class_='it-MdContent')
    if not content_div:
        logger.error("Could not find article content.")
        raise Exception("Could not find article content.")

    # --- Download images and update paths ---
    logger.info("Downloading images...")
    image_count = 0
    for img_tag in content_div.find_all('img'):
        img_url = img_tag.get('src')
        if not img_url:
            continue

        img_url = urljoin(url, img_url)
        
        try:
            img_response = requests.get(img_url, stream=True, timeout=30)
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
            logger.debug(f"Downloaded image: {img_name}")
            image_count += 1

            # If the image is wrapped in a link, unwrap it to prevent linked markdown image
            if img_tag.parent.name == 'a':
                img_tag.parent.unwrap()

        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to download {img_url}: {e}")

    logger.info(f"Downloaded {image_count} images")

    # --- Convert HTML to Markdown ---
    logger.info("Converting to Markdown...")
    # Use the modified HTML string for conversion
    markdown_content = md(str(content_div), heading_style="ATX")

    # --- Save Markdown file ---
    with open(md_filename, 'w', encoding='utf-8') as f:
        f.write(markdown_content)

    logger.info(f"Successfully downloaded article to '{article_output_dir}'")
    return article_output_dir, sanitized_title

@download_bp.route('/download', methods=['POST'])
@cross_origin()
def download_article():
    import traceback
    import logging
    
    # ログ設定
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("=== DOWNLOAD REQUEST START ===")
        logger.info("Download request received")
        
        # リクエストデータの取得
        try:
            data = request.get_json()
            logger.info(f"Request data received: {data}")
        except Exception as json_error:
            logger.error(f"Failed to parse JSON: {json_error}")
            return jsonify({'error': 'JSONの解析に失敗しました'}), 400
        
        if not data or 'url' not in data:
            logger.error("No URL provided in request")
            return jsonify({'error': 'URLが指定されていません'}), 400
        
        url = data['url']
        logger.info(f"Processing URL: {url}")
        
        # URLの簡単な検証
        if not url or not isinstance(url, str):
            logger.error("Invalid URL format")
            return jsonify({'error': '有効なURLを入力してください'}), 400
        
        if 'qiita.com' not in url:
            logger.error("Not a Qiita URL")
            return jsonify({'error': 'QiitaのURLを入力してください'}), 400
        
        # 一時ディレクトリを作成
        try:
            logger.info("Creating temporary directory...")
            temp_dir = tempfile.mkdtemp()
            logger.info(f"Created temp directory: {temp_dir}")
            
            try:
                # 記事をダウンロード
                logger.info("=== STARTING ARTICLE DOWNLOAD ===")
                logger.info("Entering download_article function")
                logger.info("Starting article download")
                
                try:
                    article_dir, article_title = download_qiita_article(url, temp_dir)
                    logger.info(f"Article downloaded successfully to: {article_dir}")
                    logger.info(f"Article title: {article_title}")
                except Exception as download_error:
                    logger.error(f"Article download failed: {str(download_error)}")
                    logger.error(f"Download traceback: {traceback.format_exc()}")
                    return jsonify({'error': f'記事のダウンロードに失敗しました: {str(download_error)}'}), 500
                
                # ZIPファイルを作成
                logger.info("=== STARTING ZIP CREATION ===")
                zip_filename = f"{article_title}.zip"
                zip_path = os.path.join(temp_dir, zip_filename)
                logger.info(f"Creating ZIP file: {zip_path}")
                
                try:
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for root, dirs, files in os.walk(article_dir):
                            for file in files:
                                file_path = os.path.join(root, file)
                                # ZIP内でのパスを相対パスにする
                                arcname = os.path.relpath(file_path, temp_dir)
                                zipf.write(file_path, arcname)
                                logger.debug(f"Added to ZIP: {arcname}")
                    
                    logger.info("ZIP file created successfully")
                    
                    # ファイルサイズを確認
                    zip_size = os.path.getsize(zip_path)
                    logger.info(f"ZIP file size: {zip_size} bytes")
                    
                except Exception as zip_error:
                    logger.error(f"ZIP creation failed: {str(zip_error)}")
                    logger.error(f"ZIP traceback: {traceback.format_exc()}")
                    return jsonify({'error': f'ZIPファイルの作成に失敗しました: {str(zip_error)}'}), 500
                
                # ZIPファイルを送信
                logger.info("=== STARTING FILE SEND ===")
                logger.info(f"Sending file: {zip_path}")
                
                try:
                    return send_file(
                        zip_path,
                        as_attachment=True,
                        download_name=zip_filename,
                        mimetype='application/zip'
                    )
                except Exception as send_error:
                    logger.error(f"File send failed: {str(send_error)}")
                    logger.error(f"Send traceback: {traceback.format_exc()}")
                    return jsonify({'error': f'ファイルの送信に失敗しました: {str(send_error)}'}), 500
                
            except Exception as e:
                logger.error(f"Download error: {str(e)}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                return jsonify({'error': f'ダウンロードに失敗しました: {str(e)}'}), 500
            finally:
                # 一時ディレクトリをクリーンアップ
                try:
                    logger.info("Cleaning up temporary directory...")
                    shutil.rmtree(temp_dir)
                    logger.info("Temp directory cleaned up")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup temp directory: {cleanup_error}")
                    
        except Exception as temp_error:
            logger.error(f"Failed to create temp directory: {temp_error}")
            return jsonify({'error': '一時ディレクトリの作成に失敗しました'}), 500
                
    except Exception as e:
        logger.error(f"Request error: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': 'リクエストの処理に失敗しました'}), 500

