import base64
import os
import logging
from typing import Optional

from docx import Document
import fitz  # PyMuPDF
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Initialize OpenAI client
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("OPENAI_API_KEY not set")

client = OpenAI(api_key=api_key)

# Configuration
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_PDF_PAGES = 50
MAX_TEXT_LENGTH = 100000  # 100k characters


def extract_text_from_file(file_path: str, file_extension: str) -> str:
    try:
        ext = file_extension.lower().strip()

        # Validate file exists and is readable
        if not os.path.exists(file_path):
            raise ValueError(f"File not found: {file_path}")

        if not os.access(file_path, os.R_OK):
            raise ValueError(f"File not readable: {file_path}")

        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise ValueError("File is empty")

        # Route to appropriate extractor
        if ext == "docx":
            return _extract_from_docx(file_path, file_size)
        elif ext == "pdf":
            return _extract_from_pdf(file_path, file_size)
        elif ext == "txt":
            return _extract_from_txt(file_path, file_size)
        elif ext in ("png", "jpg", "jpeg"):
            return _extract_from_image(file_path, file_size, ext)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

    except Exception as e:
        logger.error(f"Error extracting text from {file_path}: {e}")
        raise RuntimeError(f"Failed to extract text: {str(e)}")


def _extract_from_docx(file_path: str, file_size: int) -> str:
    try:
        doc = Document(file_path)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

        if not paragraphs:
            logger.warning(f"No text found in DOCX: {file_path}")
            return ""

        text = "\n".join(paragraphs)

        # Limit text length
        if len(text) > MAX_TEXT_LENGTH:
            logger.warning(f"Text truncated from {len(text)} to {MAX_TEXT_LENGTH} characters")
            text = text[:MAX_TEXT_LENGTH]

        return text

    except Exception as e:
        logger.error(f"DOCX extraction error: {e}")
        raise RuntimeError(f"Failed to extract DOCX: {str(e)}")


def _extract_from_pdf(file_path: str, file_size: int) -> str:
    try:
        doc = fitz.open(file_path)

        page_count = doc.page_count
        if page_count > MAX_PDF_PAGES:
            logger.warning(f"PDF has {page_count} pages, limiting to {MAX_PDF_PAGES}")
            page_count = MAX_PDF_PAGES

        # Extract text from pages
        pages = []
        for i in range(page_count):
            try:
                page = doc[i]
                page_text = page.get_text().strip()
                if page_text:
                    pages.append(page_text)
            except Exception as e:
                logger.warning(f"Failed to extract page {i}: {e}")
                continue

        doc.close()

        if not pages:
            logger.warning(f"No text found in PDF: {file_path}")
            return ""

        text = "\n\n".join(pages)

        # Limit text length
        if len(text) > MAX_TEXT_LENGTH:
            logger.warning(f"Text truncated from {len(text)} to {MAX_TEXT_LENGTH} characters")
            text = text[:MAX_TEXT_LENGTH]

        return text

    except Exception as e:
        logger.error(f"PDF extraction error: {e}")
        raise RuntimeError(f"Failed to extract PDF: {str(e)}")


def _extract_from_txt(file_path: str, file_size: int) -> str:
    try:
        encodings = ['utf-8', 'utf-16', 'latin-1', 'cp1252']

        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    text = f.read().strip()

                if text:
                    # Limit text length
                    if len(text) > MAX_TEXT_LENGTH:
                        logger.warning(f"Text truncated from {len(text)} to {MAX_TEXT_LENGTH} characters")
                        text = text[:MAX_TEXT_LENGTH]

                    return text
            except UnicodeDecodeError:
                continue

        logger.warning(f"Could not decode text file: {file_path}")
        return ""

    except Exception as e:
        logger.error(f"TXT extraction error: {e}")
        raise RuntimeError(f"Failed to extract TXT: {str(e)}")


def _extract_from_image(file_path: str, file_size: int, ext: str) -> str:
    try:
        # Check image size
        if file_size > MAX_IMAGE_SIZE:
            raise ValueError(
                f"Image too large: {file_size / (1024 * 1024):.1f}MB (max {MAX_IMAGE_SIZE / (1024 * 1024)}MB)")

        # Read and encode image
        with open(file_path, "rb") as f:
            image_data = f.read()

        image_b64 = base64.b64encode(image_data).decode("utf-8")

        # Use OpenAI Vision API for OCR
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Extract all readable text from this image. Output only the extracted text, no commentary or description."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/{ext};base64,{image_b64}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=2000
        )

        text = response.choices[0].message.content.strip()

        if not text or len(text) < 10:
            logger.warning(f"Little or no text extracted from image: {file_path}")
            return ""

        return text

    except Exception as e:
        logger.error(f"Image extraction error: {e}")
        raise RuntimeError(f"Failed to extract from image: {str(e)}")


def validate_extracted_text(text: str) -> bool:
    if not text or not text.strip():
        return False

    if len(text.strip()) < 10:
        return False
    unique_chars = len(set(text))
    if unique_chars < 5:
        return False

    return True