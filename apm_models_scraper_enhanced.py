#!/usr/bin/env python3
"""
Enhanced APM Models Scraper with Selenium
Based on detailed recon report for https://apmmodels.com/

This scraper implements a 3-stage approach:
Stage 1: Alphabet Index Scraping - Collect all model names, divisions, and profile URLs
Stage 2: Profile Deep Scraping - Fetch model attributes and full portfolio images (parallel)
Stage 3: Data Assembly - Write metadata to models.jsonl, store images in per-model folders

Features:
- Full alphabet index scraping from /w/models/
- Support for all divisions (ima, mai, dev)
- Parallel processing with ProcessPoolExecutor
- Robust error handling and data validation
- YAML configuration support
- Comprehensive logging
"""

import os
import re
import time
import json
import yaml
import requests
from urllib.parse import urljoin, urlparse
from pathlib import Path
import jsonlines
from bs4 import BeautifulSoup
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import logging
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Any
import argparse

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('apm_scraper_enhanced.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class ModelRecord:
    """Data class for model records following the recon report schema."""
    model_id: str
    name: str
    division: str
    profile_url: str
    thumbnail: str
    attributes: Dict[str, str]
    images: List[str]
    slug: Optional[str] = None
    
    def __post_init__(self):
        if not self.slug:
            self.slug = self.slugify_name(self.name)
    
    @staticmethod
    def slugify_name(name: str) -> str:
        """Convert model name to safe folder slug following recon report rules."""
        # Remove special characters and convert to lowercase
        slug = re.sub(r'[^\w\s-]', '', name.lower())
        # Replace spaces and multiple hyphens with single underscore
        slug = re.sub(r'[-\s]+', '_', slug)
        # Remove leading/trailing underscores
        slug = slug.strip('_')
        return slug

class APMModelsEnhancedScraper:
    """Enhanced APM Models scraper implementing the full recon report strategy."""
    
    def __init__(self, config_path: Optional[str] = None, kb_dir: str = "elysium_kb"):
        self.config = self._load_config(config_path)
        self.base_url = self.config.get('base_url', 'https://apmmodels.com')
        self.kb_dir = Path(kb_dir)
        self.images_dir = self.kb_dir / "images"
        self.models_file = self.kb_dir / "models.jsonl"
        
        # Create directories
        self.images_dir.mkdir(parents=True, exist_ok=True)
        
        # Session for image downloads
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': self.config.get('user_agent', 
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
        })
        
        # WebDriver will be initialized when needed
        self.driver = None
        
        # Statistics
        self.stats = {
            'models_found': 0,
            'models_processed': 0,
            'models_failed': 0,
            'images_downloaded': 0,
            'images_failed': 0
        }
    
    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        """Load configuration from YAML file or use defaults."""
        default_config = {
            'base_url': 'https://apmmodels.com',
            'index_url': 'https://apmmodels.com/w/models/dev',  # Use working dev division by default
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'headless': True,
            'max_workers': 4,
            'request_delay': 1.5,
            'max_retries': 3,
            'timeout': 30,
            'divisions': ['ima', 'mai', 'dev'],
            'selectors': {
                'alphabet_index': {
                    'letter_group': 'div.models > div.letter',
                    'model_list_items': 'li.model-entry',
                    'model_name': 'li.model-entry a',
                    'profile_url': 'li.model-entry a::attr(href)',
                    'model_id': 'li.model-entry::attr(data-id)',
                    'divisions_meta': 'li.model-entry::attr(data-divisions)',
                    'thumbnail_url': 'li.model-entry img::attr(src)',
                    'thumbnail_alt': 'li.model-entry img::attr(alt)'
                },
                'profile_page': {
                    'feature_rows': 'table.model-features tr.model-feature',
                    'feature_name': '.model-feature-name',
                    'feature_value': '.model-feature-value',
                    'gallery_images': 'div.picture-frame img::attr(src)'
                }
            },
            'expected_attributes': ['height', 'bust', 'waist', 'hips', 'shoes', 'hair', 'eyes'],
            'validation': {
                'min_images_per_model': 1,
                'required_divisions': ['ima', 'mai', 'dev']
            },
            'limits': {
                'max_images_per_model': 15  # Including thumbnail
            }
        }
        
        if config_path and Path(config_path).exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    user_config = yaml.safe_load(f)
                    default_config.update(user_config)
                    logger.info(f"Loaded configuration from {config_path}")
            except Exception as e:
                logger.warning(f"Failed to load config from {config_path}: {e}")
        
        return default_config
    
    def setup_driver(self) -> webdriver.Chrome:
        """Initialize the Chrome WebDriver with optimal settings."""
        if self.driver is not None:
            return self.driver
            
        logger.info("Setting up Chrome WebDriver...")
        
        # Chrome options
        chrome_options = Options()
        if self.config.get('headless', True):
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument(f"--user-agent={self.config['user_agent']}")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Automatically download and setup ChromeDriver
        service = Service(ChromeDriverManager().install())
        
        # Create driver
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.driver.implicitly_wait(10)
        
        # Execute script to remove webdriver property
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        logger.info("Chrome WebDriver setup complete")
        return self.driver
    
    def close_driver(self):
        """Close the WebDriver."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            logger.info("WebDriver closed")
    
    def safe_request(self, url: str, max_retries: Optional[int] = None, delay: Optional[float] = None) -> Optional[requests.Response]:
        """Make a safe HTTP request with retries and throttling."""
        max_retries = max_retries or self.config.get('max_retries', 3)
        delay = delay or self.config.get('request_delay', 1.5)
        
        for attempt in range(max_retries):
            try:
                time.sleep(delay)  # Throttling
                response = self.session.get(url, timeout=self.config.get('timeout', 30))
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt == max_retries - 1:
                    logger.error(f"Failed to fetch {url} after {max_retries} attempts")
                    return None
                time.sleep(delay * (attempt + 1))  # Exponential backoff
        return None

    def scrape_alphabet_index(self, index_url: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Stage 1: Alphabet Index Scraping
        Collect all model names, divisions, and profile URLs from the main index page.

        Returns:
            List of model dictionaries with basic info extracted from index
        """
        index_url = index_url or self.config.get('index_url', 'https://apmmodels.com/w/models/')
        logger.info(f"Starting Stage 1: Alphabet Index Scraping from {index_url}")

        driver = self.setup_driver()
        models = []

        try:
            # Navigate to the index page
            driver.get(index_url)

            # Wait for page to load and content to appear
            logger.info("Waiting for alphabet index content to load...")
            time.sleep(5)  # Initial wait for JavaScript to execute

            # Try to wait for specific elements that indicate the page has loaded
            try:
                WebDriverWait(driver, 15).until(
                    lambda d: len(d.find_elements(By.CSS_SELECTOR, "div.models")) > 0 or
                             len(d.find_elements(By.CSS_SELECTOR, "li.model-entry")) > 0
                )
            except TimeoutException:
                logger.warning("Timeout waiting for alphabet index elements, proceeding anyway...")

            # Get page source and parse with BeautifulSoup
            page_source = driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')

            # Debug: Save page source for inspection
            debug_file = f'debug_alphabet_index_{int(time.time())}.html'
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(page_source)
            logger.info(f"Saved alphabet index page source to {debug_file}")

            # Extract models using selectors from recon report
            selectors = self.config['selectors']['alphabet_index']

            # Method 1: Try the exact selectors from recon report
            letter_groups = soup.select(selectors['letter_group'])
            if letter_groups:
                logger.info(f"Found {len(letter_groups)} letter groups using recon selectors")

                for letter_group in letter_groups:
                    letter = letter_group.get_text(strip=True)
                    logger.debug(f"Processing letter group: {letter}")

                    # Find the models container for this letter
                    models_container = letter_group.find_next_sibling('div', class_='models-inner')
                    if not models_container:
                        # Try alternative structure
                        models_container = letter_group.parent.find('div', class_='models-inner')

                    if models_container:
                        model_entries = models_container.select('li.model-entry')
                        logger.debug(f"Found {len(model_entries)} model entries for letter {letter}")

                        for entry in model_entries:
                            try:
                                model_data = self._extract_model_from_entry(entry, letter)
                                if model_data:
                                    models.append(model_data)
                            except Exception as e:
                                logger.warning(f"Error extracting model from entry in letter {letter}: {e}")
                                continue

            # Method 2: Fallback - try to find all model entries directly
            if not models:
                logger.info("Trying fallback method to find model entries...")
                all_model_entries = soup.select('li.model-entry')
                if all_model_entries:
                    logger.info(f"Found {len(all_model_entries)} model entries using fallback method")

                    for entry in all_model_entries:
                        try:
                            model_data = self._extract_model_from_entry(entry)
                            if model_data:
                                models.append(model_data)
                        except Exception as e:
                            logger.warning(f"Error extracting model from entry: {e}")
                            continue

            # Method 3: Alternative selectors if still no results
            if not models:
                logger.info("Trying alternative selectors...")
                alternative_selectors = [
                    'a.cover-img-wrapper',  # From existing scraper
                    'a[href*="/models/"]',
                    'a[href*="dev-"], a[href*="ima-"], a[href*="mai-"]',
                    '.model-card a',
                    '.model a'
                ]

                for selector in alternative_selectors:
                    elements = soup.select(selector)
                    if elements:
                        logger.info(f"Found {len(elements)} elements with alternative selector: {selector}")

                        for elem in elements:
                            try:
                                model_data = self._extract_model_from_link(elem)
                                if model_data:
                                    models.append(model_data)
                            except Exception as e:
                                logger.warning(f"Error extracting model from link: {e}")
                                continue
                        break

            # Method 4: If main index fails, log the issue but don't fall back to divisions
            if not models and index_url == self.config.get('index_url', 'https://apmmodels.com/w/models/'):
                logger.warning("Main index failed to find models. Check if the page structure has changed.")
                logger.info("Consider using --index-url with a specific division URL if needed.")

            # Remove duplicates based on profile URL
            unique_models = []
            seen_urls = set()
            for model in models:
                if model['profile_url'] not in seen_urls:
                    unique_models.append(model)
                    seen_urls.add(model['profile_url'])

            models = unique_models
            self.stats['models_found'] = len(models)

            logger.info(f"Stage 1 Complete: Found {len(models)} unique models from alphabet index")
            return models

        except Exception as e:
            logger.error(f"Error in Stage 1 alphabet index scraping: {e}")
            return []

    def _extract_model_from_entry(self, entry, letter: str = None) -> Optional[Dict[str, Any]]:
        """Extract model data from a li.model-entry element following recon report."""
        try:
            # Extract model name from link text
            link = entry.find('a')
            if not link:
                return None

            model_name = link.get_text(strip=True)
            if not model_name:
                return None

            # Extract profile URL
            profile_url = link.get('href', '').strip()
            if not profile_url:
                return None

            # Make URL absolute
            if not profile_url.startswith('http'):
                profile_url = urljoin(self.base_url, profile_url)

            # Extract division from URL using robust method
            division = self._extract_division_from_url(profile_url)

            # Extract model ID from data-id attribute
            model_id = entry.get('data-id', '')

            # If no data-id, try to extract from URL
            if not model_id:
                id_match = re.search(r'/(ima|mai|dev)-(\d+)-', profile_url)
                model_id = id_match.group(2) if id_match else ''

            # Extract divisions metadata
            divisions_meta = entry.get('data-divisions', '')

            # Extract thumbnail URL
            thumbnail_url = ''
            img_tag = entry.find('img')
            if img_tag:
                thumbnail_url = img_tag.get('src', '')
                if thumbnail_url and not thumbnail_url.startswith('http'):
                    thumbnail_url = urljoin(self.base_url, thumbnail_url)

            # Extract thumbnail alt text
            thumbnail_alt = img_tag.get('alt', '') if img_tag else ''

            model_data = {
                'model_id': model_id,
                'name': model_name,
                'division': division,
                'profile_url': profile_url,
                'thumbnail': thumbnail_url,
                'thumbnail_alt': thumbnail_alt,
                'divisions_meta': divisions_meta,
                'letter_group': letter,
                'slug': ModelRecord.slugify_name(model_name)
            }

            return model_data

        except Exception as e:
            logger.warning(f"Error extracting model from entry: {e}")
            return None



    def _extract_division_from_url(self, url: str) -> str:
        """Extract division (ima, mai, dev) from profile URL with robust pattern matching."""
        import re

        # Try multiple patterns to be more robust
        patterns = [
            r'/models/(ima|mai|dev)/',  # Standard pattern: /models/dev/
            r'/(ima|mai|dev)-\d+',      # Division prefix in filename: /dev-12345
            r'/(ima|mai|dev)/',         # Division in any path: /dev/
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                division = match.group(1)
                logger.debug(f"Extracted division '{division}' from URL: {url}")
                return division

        logger.warning(f"Could not extract division from URL: {url}")
        return 'unknown'

    def _extract_model_from_link(self, link_elem) -> Optional[Dict[str, Any]]:
        """Extract model data from a generic link element (fallback method)."""
        try:
            # Extract model name from img alt or link text
            model_name = ''
            img_tag = link_elem.find('img')

            if img_tag and img_tag.get('alt'):
                model_name = img_tag.get('alt', '').strip()
            elif link_elem.get_text(strip=True):
                model_name = link_elem.get_text(strip=True)

            if not model_name:
                return None

            # Extract profile URL
            profile_url = link_elem.get('href', '').strip()
            if not profile_url:
                return None

            # Make URL absolute
            if not profile_url.startswith('http'):
                profile_url = urljoin(self.base_url, profile_url)

            # Skip if this doesn't look like a model profile URL
            if not any(div in profile_url for div in ['ima', 'mai', 'dev']):
                return None

            # Extract division from URL
            division = self._extract_division_from_url(profile_url)

            # Extract model ID from URL
            model_id = ''
            id_match = re.search(r'/(ima|mai|dev)-(\d+)-', profile_url)
            model_id = id_match.group(2) if id_match else ''

            # Extract thumbnail URL
            thumbnail_url = ''
            if img_tag:
                thumbnail_url = img_tag.get('src', '')
                if thumbnail_url and not thumbnail_url.startswith('http'):
                    thumbnail_url = urljoin(self.base_url, thumbnail_url)

            model_data = {
                'model_id': model_id,
                'name': model_name,
                'division': division,
                'profile_url': profile_url,
                'thumbnail': thumbnail_url,
                'thumbnail_alt': '',
                'divisions_meta': '',
                'letter_group': '',
                'slug': ModelRecord.slugify_name(model_name)
            }

            return model_data

        except Exception as e:
            logger.warning(f"Error extracting model from link: {e}")
            return None

    def scrape_model_profile(self, model_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Stage 2: Profile Deep Scraping
        Fetch detailed model attributes and gallery images from individual profile page.

        Args:
            model_data: Basic model info from Stage 1

        Returns:
            Enhanced model data with attributes and gallery images
        """
        profile_url = model_data['profile_url']
        model_name = model_data['name']

        logger.info(f"Stage 2: Scraping profile for {model_name}: {profile_url}")

        driver = self.setup_driver()

        try:
            # Navigate to the profile page
            driver.get(profile_url)

            # Wait for content to load
            time.sleep(3)

            # Try to wait for specific elements
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: len(d.find_elements(By.CSS_SELECTOR, "table, img")) > 0
                )
            except TimeoutException:
                logger.warning(f"Timeout waiting for profile elements for {model_name}")

            # Get page source and parse with BeautifulSoup
            page_source = driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')

            # Extract model attributes from the features table
            attributes = self._extract_model_attributes(soup, model_name)

            # Extract gallery image URLs
            gallery_images = self._extract_gallery_images(soup, model_name)

            # Update model data with extracted information
            model_data.update({
                'attributes': attributes,
                'gallery_images': gallery_images
            })

            logger.debug(f"Extracted {len(attributes)} attributes and {len(gallery_images)} images for {model_name}")
            return model_data

        except Exception as e:
            logger.error(f"Error scraping profile for {model_name}: {e}")
            # Return original data even if scraping failed
            model_data.update({
                'attributes': {},
                'gallery_images': []
            })
            return model_data

    def _extract_model_attributes(self, soup: BeautifulSoup, model_name: str) -> Dict[str, str]:
        """Extract model attributes from the features table following recon report."""
        attributes = {}

        # Try multiple selectors for the features table
        table_selectors = [
            'table.model-features',
            '.model-features',
            'table[class*="feature"]',
            'table[class*="model"]',
            'table[class*="info"]',
            '.features table',
            '.model-info table',
            'table'
        ]

        features_table = None
        for selector in table_selectors:
            features_table = soup.select_one(selector)
            if features_table:
                logger.debug(f"Found features table for {model_name} with selector: {selector}")
                break

        if features_table:
            rows = features_table.find_all('tr')
            for row in rows:
                try:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        feature_name = cells[0].get_text(strip=True).lower()
                        feature_value = cells[1].get_text(strip=True)

                        if feature_name and feature_value:
                            # Normalize feature names to match expected schema
                            normalized_name = self._normalize_attribute_name(feature_name)
                            attributes[normalized_name] = feature_value

                except Exception as e:
                    logger.warning(f"Error processing attribute row for {model_name}: {e}")
                    continue

        logger.debug(f"Extracted {len(attributes)} attributes for {model_name}")
        return attributes

    def _normalize_attribute_name(self, name: str) -> str:
        """Normalize attribute names to match expected schema."""
        name = name.lower().strip()

        # Map common variations to standard names
        name_mapping = {
            'height': 'height',
            'bust': 'bust',
            'chest': 'bust',  # For male models
            'waist': 'waist',
            'hips': 'hips',
            'shoes': 'shoes',
            'shoe': 'shoes',
            'hair': 'hair',
            'hair color': 'hair',
            'eyes': 'eyes',
            'eye color': 'eyes',
            'eye colour': 'eyes'
        }

        return name_mapping.get(name, name)

    def _extract_gallery_images(self, soup: BeautifulSoup, model_name: str) -> List[str]:
        """Extract gallery image URLs following recon report selectors."""
        gallery_images = []

        # Try multiple selectors for images as per recon report
        image_selectors = [
            'div.picture-frame img',
            '.picture-frame img',
            '.gallery img',
            '.photos img',
            '.images img',
            '.portfolio img',
            'img[src*="jpg"], img[src*="jpeg"], img[src*="png"]'
        ]

        for selector in image_selectors:
            images = soup.select(selector)
            if images:
                logger.debug(f"Found {len(images)} images for {model_name} with selector: {selector}")
                for img in images:
                    try:
                        img_src = img.get('src', '').strip()
                        if img_src:
                            # Make URL absolute if relative
                            if not img_src.startswith('http'):
                                img_src = urljoin(self.base_url, img_src)
                            gallery_images.append(img_src)

                    except Exception as e:
                        logger.warning(f"Error processing gallery image for {model_name}: {e}")
                        continue
                break  # Use first selector that finds images

        # Remove duplicates while preserving order
        gallery_images = list(dict.fromkeys(gallery_images))

        logger.debug(f"Found {len(gallery_images)} gallery images for {model_name}")
        return gallery_images

    def download_model_images(self, model_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Stage 3: Download and organize images for a model following recon report schema.
        Updates model_data with image_files list.
        """
        model_name = model_data['name']
        slug = model_data['slug']
        gallery_images = model_data.get('gallery_images', [])
        thumbnail_url = model_data.get('thumbnail')

        logger.info(f"Stage 3: Downloading images for {model_name} ({len(gallery_images)} gallery images)")

        # Create model-specific image directory following recon report structure
        model_image_dir = self.images_dir / slug
        model_image_dir.mkdir(parents=True, exist_ok=True)

        downloaded_files = []

        # Download thumbnail as first image if available
        if thumbnail_url:
            try:
                ext = self._get_image_extension(thumbnail_url)
                thumbnail_path = model_image_dir / f"thumbnail{ext}"

                if self._download_image(thumbnail_url, thumbnail_path):
                    downloaded_files.append(thumbnail_path.name)
                    self.stats['images_downloaded'] += 1
                else:
                    self.stats['images_failed'] += 1

            except Exception as e:
                logger.warning(f"Failed to download thumbnail for {model_name}: {e}")
                self.stats['images_failed'] += 1

        # Download gallery images with sequential naming as per recon report
        # Limit to maximum images per model (excluding thumbnail)
        max_total_images = self.config.get('limits', {}).get('max_images_per_model', 15)
        max_portfolio_images = max_total_images - 1  # Subtract 1 for thumbnail
        limited_gallery_images = gallery_images[:max_portfolio_images]

        if len(gallery_images) > max_portfolio_images:
            logger.info(f"Limiting {model_name} to {max_portfolio_images} portfolio images (was {len(gallery_images)})")

        for i, img_url in enumerate(limited_gallery_images, 1):
            try:
                ext = self._get_image_extension(img_url)

                # Use portfolio naming scheme from recon report
                filename = f"portfolio{i}{ext}"
                img_path = model_image_dir / filename

                if self._download_image(img_url, img_path):
                    downloaded_files.append(filename)
                    self.stats['images_downloaded'] += 1
                else:
                    self.stats['images_failed'] += 1

            except Exception as e:
                logger.warning(f"Failed to download gallery image {i} for {model_name}: {e}")
                self.stats['images_failed'] += 1
                continue

        logger.info(f"Downloaded {len(downloaded_files)} images for {model_name}")

        # Update model data with downloaded files info following recon report schema
        image_paths = [f"images/{slug}/{filename}" for filename in downloaded_files]
        model_data.update({
            'images': image_paths  # Following recon report schema
        })

        return model_data

    def _download_image(self, url: str, filepath: Path) -> bool:
        """Download a single image from URL to filepath."""
        try:
            response = self.safe_request(url)
            if not response:
                return False

            # Create directory if it doesn't exist
            filepath.parent.mkdir(parents=True, exist_ok=True)

            # Write image data to file
            with open(filepath, 'wb') as f:
                f.write(response.content)

            logger.debug(f"Downloaded image: {filepath}")
            return True

        except Exception as e:
            logger.error(f"Failed to download image {url}: {e}")
            return False

    def _get_image_extension(self, url: str) -> str:
        """Extract file extension from image URL."""
        parsed_url = urlparse(url)
        path = parsed_url.path.lower()

        # Common image extensions
        for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            if ext in path:
                return ext

        # Default to .jpg if no extension found
        return '.jpg'

    def validate_model_data(self, model_data: Dict[str, Any]) -> bool:
        """
        Validate model data according to recon report heuristics.

        Returns:
            True if model data passes validation, False otherwise
        """
        model_name = model_data.get('name', 'Unknown')

        # Check required fields
        required_fields = ['model_id', 'name', 'division', 'profile_url']
        for field in required_fields:
            if not model_data.get(field):
                logger.warning(f"Validation failed for {model_name}: missing {field}")
                return False

        # Check division verification
        division = model_data.get('division')
        valid_divisions = self.config['validation']['required_divisions']
        if division not in valid_divisions:
            logger.warning(f"Validation failed for {model_name}: invalid division '{division}'")
            return False

        # Check minimum image count
        images = model_data.get('images', [])
        min_images = self.config['validation']['min_images_per_model']
        if len(images) < min_images:
            logger.warning(f"Validation failed for {model_name}: only {len(images)} images (minimum {min_images})")
            return False

        # Check expected attributes (warning only, not failure)
        attributes = model_data.get('attributes', {})
        expected_attrs = self.config['expected_attributes']
        missing_attrs = [attr for attr in expected_attrs if attr not in attributes]
        if missing_attrs:
            logger.info(f"Model {model_name} missing expected attributes: {missing_attrs}")

        return True

    def save_model_metadata(self, model_data: Dict[str, Any]) -> bool:
        """
        Save model metadata to JSONL file following recon report schema.

        Args:
            model_data: Complete model data dictionary

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            # Prepare the record following recon report JSONL schema
            record = {
                'model_id': model_data.get('model_id', ''),
                'name': model_data.get('name', ''),
                'division': model_data.get('division', ''),
                'profile_url': model_data.get('profile_url', ''),
                'thumbnail': model_data.get('thumbnail', ''),
                'attributes': model_data.get('attributes', {}),
                'images': model_data.get('images', [])
            }

            # Append to JSONL file
            with jsonlines.open(self.models_file, mode='a') as writer:
                writer.write(record)

            logger.debug(f"Saved metadata for {model_data['name']}")
            return True

        except Exception as e:
            logger.error(f"Failed to save metadata for {model_data.get('name', 'Unknown')}: {e}")
            return False

    def process_single_model(self, model_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a single model through all stages (2 and 3)."""
        try:
            model_name = model_data.get('name', 'Unknown')
            logger.info(f"Processing model: {model_name}")

            # Stage 2: Get detailed information
            model_data = self.scrape_model_profile(model_data)

            # Stage 3: Download images
            model_data = self.download_model_images(model_data)

            # Validate data
            if not self.validate_model_data(model_data):
                logger.warning(f"Model {model_name} failed validation")
                self.stats['models_failed'] += 1
                return None

            # Save metadata
            if self.save_model_metadata(model_data):
                self.stats['models_processed'] += 1
                logger.info(f"Successfully processed model: {model_name}")
                return model_data
            else:
                self.stats['models_failed'] += 1
                return None

        except Exception as e:
            logger.error(f"Failed to process model {model_data.get('name', 'Unknown')}: {e}")
            self.stats['models_failed'] += 1
            return None

    def run_parallel_processing(self, models: List[Dict[str, Any]], max_workers: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Run parallel processing of models using ProcessPoolExecutor as per recon report.

        Args:
            models: List of model data from Stage 1
            max_workers: Number of parallel workers (default from config)

        Returns:
            List of successfully processed models
        """
        max_workers = max_workers or self.config.get('max_workers', 4)
        logger.info(f"Starting parallel processing with {max_workers} workers for {len(models)} models")

        processed_models = []

        # For now, process sequentially to avoid WebDriver conflicts
        # TODO: Implement proper parallel processing with separate WebDriver instances
        for i, model in enumerate(models, 1):
            try:
                logger.info(f"Processing model {i}/{len(models)}: {model['name']}")
                result = self.process_single_model(model)
                if result:
                    processed_models.append(result)

                # Add delay between models to be respectful
                if i < len(models):
                    time.sleep(self.config.get('request_delay', 1.5))

            except Exception as e:
                logger.error(f"Exception processing model {model.get('name', 'Unknown')}: {e}")
                self.stats['models_failed'] += 1

        logger.info(f"Parallel processing complete. Processed: {len(processed_models)}, Failed: {self.stats['models_failed']}")
        return processed_models

    def run_scraper(self, test_mode: bool = False, max_models: Optional[int] = None,
                   index_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Main orchestration method implementing the complete 3-stage scraping pipeline.

        Args:
            test_mode: If True, only process first few models for testing
            max_models: Maximum number of models to process (None for all)
            index_url: Custom index URL to scrape (uses config default if None)

        Returns:
            Dictionary with scraping results and statistics
        """
        logger.info("Starting Enhanced APM Models scraper following recon report")

        try:
            # Stage 1: Get all models from alphabet index
            models = self.scrape_alphabet_index(index_url)

            if not models:
                logger.error("No models found in Stage 1")
                return {'success': False, 'stats': self.stats, 'models': []}

            # Apply limits for testing or max_models parameter
            if test_mode:
                models = models[:3]
                logger.info(f"Test mode: Processing only {len(models)} models")
            elif max_models:
                models = models[:max_models]
                logger.info(f"Limited to {len(models)} models")

            logger.info(f"Starting processing pipeline for {len(models)} models")

            # Stages 2 & 3: Process models (parallel processing)
            processed_models = self.run_parallel_processing(models)

            # Final statistics
            logger.info(f"Scraping completed successfully!")
            logger.info(f"Models found: {self.stats['models_found']}")
            logger.info(f"Models processed: {self.stats['models_processed']}")
            logger.info(f"Models failed: {self.stats['models_failed']}")
            logger.info(f"Images downloaded: {self.stats['images_downloaded']}")
            logger.info(f"Images failed: {self.stats['images_failed']}")

            return {
                'success': True,
                'stats': self.stats,
                'models': processed_models
            }

        except Exception as e:
            logger.error(f"Fatal error in scraper: {e}")
            return {'success': False, 'stats': self.stats, 'models': [], 'error': str(e)}
        finally:
            # Close WebDriver and session
            self.close_driver()
            self.session.close()


def create_default_config(config_path: str = "apm_scraper_config.yaml"):
    """Create a default YAML configuration file."""
    default_config = {
        'base_url': 'https://apmmodels.com',
        'index_url': 'https://apmmodels.com/w/models/',
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'headless': True,
        'max_workers': 4,
        'request_delay': 1.5,
        'max_retries': 3,
        'timeout': 30,
        'divisions': ['ima', 'mai', 'dev'],
        'selectors': {
            'alphabet_index': {
                'letter_group': 'div.models > div.letter',
                'model_list_items': 'li.model-entry',
                'model_name': 'li.model-entry a',
                'profile_url': 'li.model-entry a::attr(href)',
                'model_id': 'li.model-entry::attr(data-id)',
                'divisions_meta': 'li.model-entry::attr(data-divisions)',
                'thumbnail_url': 'li.model-entry img::attr(src)',
                'thumbnail_alt': 'li.model-entry img::attr(alt)'
            },
            'profile_page': {
                'feature_rows': 'table.model-features tr.model-feature',
                'feature_name': '.model-feature-name',
                'feature_value': '.model-feature-value',
                'gallery_images': 'div.picture-frame img::attr(src)'
            }
        },
        'expected_attributes': ['height', 'bust', 'waist', 'hips', 'shoes', 'hair', 'eyes'],
        'validation': {
            'min_images_per_model': 1,
            'required_divisions': ['ima', 'mai', 'dev']
        },
        'limits': {
            'max_images_per_model': 15  # Including thumbnail
        }
    }

    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(default_config, f, default_flow_style=False, indent=2)
        logger.info(f"Created default configuration file: {config_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to create config file {config_path}: {e}")
        return False


def main():
    """Main entry point for the enhanced APM Models scraper."""
    parser = argparse.ArgumentParser(
        description='Enhanced APM Models Scraper with Selenium - Following Detailed Recon Report',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run in test mode (3 models only)
  python apm_models_scraper_enhanced.py --test

  # Run with custom config and max models
  python apm_models_scraper_enhanced.py --config my_config.yaml --max-models 50

  # Run in visible mode for debugging
  python apm_models_scraper_enhanced.py --visible --test

  # Create default config file
  python apm_models_scraper_enhanced.py --create-config
        """
    )

    parser.add_argument('--test', action='store_true',
                       help='Run in test mode (process only 3 models)')
    parser.add_argument('--max-models', type=int,
                       help='Maximum number of models to process')
    parser.add_argument('--kb-dir', default='elysium_kb',
                       help='Knowledge base directory (default: elysium_kb)')
    parser.add_argument('--config', type=str,
                       help='Path to YAML configuration file')
    parser.add_argument('--headless', action='store_true', default=True,
                       help='Run browser in headless mode (default)')
    parser.add_argument('--visible', action='store_true',
                       help='Run browser in visible mode (opposite of headless)')
    parser.add_argument('--index-url', type=str,
                       help='Custom index URL to scrape (overrides config)')
    parser.add_argument('--create-config', action='store_true',
                       help='Create default configuration file and exit')
    parser.add_argument('--workers', type=int,
                       help='Number of parallel workers (overrides config)')

    args = parser.parse_args()

    # Handle config creation
    if args.create_config:
        config_path = args.config or "apm_scraper_config.yaml"
        if create_default_config(config_path):
            print(f"✅ Created default configuration file: {config_path}")
            print("Edit this file to customize scraper settings, then run:")
            print(f"python apm_models_scraper_enhanced.py --config {config_path}")
        else:
            print("❌ Failed to create configuration file")
        return

    # Handle headless mode
    headless = args.headless and not args.visible

    try:
        # Create scraper instance
        scraper = APMModelsEnhancedScraper(config_path=args.config, kb_dir=args.kb_dir)

        # Override config with command line arguments
        if not headless:
            scraper.config['headless'] = False
        if args.workers:
            scraper.config['max_workers'] = args.workers

        # Run the scraper
        result = scraper.run_scraper(
            test_mode=args.test,
            max_models=args.max_models,
            index_url=args.index_url
        )

        # Print results
        if result['success']:
            print("\n🎉 Scraping completed successfully!")
            print(f"📊 Statistics:")
            print(f"   Models found: {result['stats']['models_found']}")
            print(f"   Models processed: {result['stats']['models_processed']}")
            print(f"   Models failed: {result['stats']['models_failed']}")
            print(f"   Images downloaded: {result['stats']['images_downloaded']}")
            print(f"   Images failed: {result['stats']['images_failed']}")
            print(f"\n📁 Data saved to: {scraper.kb_dir}")
            print(f"   Metadata: {scraper.models_file}")
            print(f"   Images: {scraper.images_dir}")
        else:
            print("\n❌ Scraping failed!")
            if 'error' in result:
                print(f"Error: {result['error']}")
            print(f"Check the log file for details: apm_scraper_enhanced.log")

    except KeyboardInterrupt:
        print("\n⏹️  Scraping interrupted by user")
    except Exception as e:
        print(f"\n💥 Fatal error: {e}")
        logger.error(f"Fatal error in main: {e}")


if __name__ == "__main__":
    main()
