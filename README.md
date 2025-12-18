# APM Models Enhanced Scraper

A robust, production-ready web scraper for extracting model portfolios from apmmodels.com. This scraper uses Selenium WebDriver for JavaScript-heavy pages and implements a three-stage pipeline for comprehensive data extraction.

## Features

- **Three-Stage Pipeline**: Alphabet index scraping → Profile deep scraping → Image downloading
- **Selenium-Powered**: Handles dynamic JavaScript content with Chrome WebDriver
- **Parallel Processing**: Efficient multi-worker processing for large datasets
- **Robust Error Handling**: Retry logic, exponential backoff, and graceful degradation
- **YAML Configuration**: Flexible configuration system for all scraper parameters
- **Comprehensive Logging**: Detailed logs for debugging and monitoring
- **Data Validation**: Built-in validation against expected data schemas
- **Division Support**: Handles all model divisions (ima, mai, dev)

## Installation

### Prerequisites

- Python 3.7 or higher
- Google Chrome browser installed
- Internet connection

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Required Python Packages

```
selenium>=4.0.0
webdriver-manager>=3.8.0
beautifulsoup4>=4.9.3
requests>=2.25.1
jsonlines>=2.0.0
pyyaml>=5.4.1
```

Or install all at once:

```bash
pip install selenium webdriver-manager beautifulsoup4 requests jsonlines pyyaml
```

## Quick Start

### Test Run (3 Models)

```bash
python apm_models_scraper_enhanced.py --test
```

### Full Run

```bash
python apm_models_scraper_enhanced.py
```

### Create Configuration File

```bash
python apm_models_scraper_enhanced.py --create-config
```

This creates `apm_scraper_config.yaml` which you can customize.

## Usage

### Basic Commands

```bash
# Test mode - process only 3 models
python apm_models_scraper_enhanced.py --test

# Process specific number of models
python apm_models_scraper_enhanced.py --max-models 50

# Use custom configuration file
python apm_models_scraper_enhanced.py --config my_config.yaml

# Run with visible browser (for debugging)
python apm_models_scraper_enhanced.py --visible --test

# Use custom knowledge base directory
python apm_models_scraper_enhanced.py --kb-dir my_data

# Scrape from specific division
python apm_models_scraper_enhanced.py --index-url https://apmmodels.com/w/models/dev

# Set number of parallel workers
python apm_models_scraper_enhanced.py --workers 8
```

### Command Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--test` | Process only 3 models for testing | False |
| `--max-models N` | Maximum number of models to process | All |
| `--kb-dir PATH` | Knowledge base directory | `elysium_kb` |
| `--config PATH` | Path to YAML configuration file | None |
| `--headless` | Run browser in headless mode | True |
| `--visible` | Run browser in visible mode | False |
| `--index-url URL` | Custom index URL to scrape | Config default |
| `--create-config` | Create default config file and exit | - |
| `--workers N` | Number of parallel workers | 4 |

## Configuration

### Configuration File Structure

The scraper uses YAML configuration for all settings:

```yaml
base_url: 'https://apmmodels.com'
index_url: 'https://apmmodels.com/w/models/dev'
headless: true
max_workers: 4
request_delay: 1.5
max_retries: 3
timeout: 30

divisions:
  - ima
  - mai
  - dev

selectors:
  alphabet_index:
    letter_group: 'div.models > div.letter'
    model_list_items: 'li.model-entry'
    # ... more selectors

expected_attributes:
  - height
  - bust
  - waist
  - hips
  - shoes
  - hair
  - eyes

validation:
  min_images_per_model: 1
  required_divisions: ['ima', 'mai', 'dev']

limits:
  max_images_per_model: 15
```

### Key Configuration Options

- **headless**: Run Chrome in headless mode (no visible browser window)
- **max_workers**: Number of parallel workers for processing
- **request_delay**: Delay between requests in seconds (be respectful to servers)
- **max_retries**: Number of retry attempts for failed requests
- **timeout**: Request timeout in seconds
- **max_images_per_model**: Limit images downloaded per model

## Output Structure

### Directory Layout

```
elysium_kb/
├── models.jsonl          # Model metadata (one JSON object per line)
└── images/
    ├── model_name_1/
    │   ├── thumbnail.jpg
    │   ├── portfolio1.jpg
    │   ├── portfolio2.jpg
    │   └── ...
    ├── model_name_2/
    │   └── ...
    └── ...
```

### JSONL Schema

Each line in `models.jsonl` contains:

```json
{
  "model_id": "12345",
  "name": "Model Name",
  "division": "dev",
  "profile_url": "https://apmmodels.com/models/dev/...",
  "thumbnail": "https://...",
  "attributes": {
    "height": "5'9\"",
    "bust": "34\"",
    "waist": "24\"",
    "hips": "35\"",
    "shoes": "8",
    "hair": "Brown",
    "eyes": "Blue"
  },
  "images": [
    "images/model_name/thumbnail.jpg",
    "images/model_name/portfolio1.jpg",
    "images/model_name/portfolio2.jpg"
  ]
}
```

## How It Works

### Stage 1: Alphabet Index Scraping

- Navigates to the models index page
- Extracts all model entries with basic information:
  - Model name
  - Division (ima/mai/dev)
  - Profile URL
  - Thumbnail URL
  - Model ID

### Stage 2: Profile Deep Scraping

For each model:
- Visits the individual profile page
- Extracts detailed attributes (height, measurements, etc.)
- Collects gallery image URLs

### Stage 3: Image Downloading

- Downloads thumbnail image
- Downloads portfolio images (sequential naming)
- Organizes images in model-specific folders
- Updates metadata with local image paths

## Logging

The scraper creates detailed logs in `apm_scraper_enhanced.log`:

```
2024-01-15 10:30:15 - INFO - Starting Enhanced APM Models scraper
2024-01-15 10:30:20 - INFO - Stage 1 Complete: Found 150 unique models
2024-01-15 10:30:25 - INFO - Processing model 1/150: Jane Doe
2024-01-15 10:30:30 - INFO - Downloaded 8 images for Jane Doe
```

## Error Handling

The scraper includes robust error handling:

- **Retry Logic**: Automatic retries with exponential backoff
- **Validation**: Data validation before saving
- **Graceful Degradation**: Continues processing even if individual models fail
- **Debug Output**: Saves page HTML for failed scrapes
- **Comprehensive Statistics**: Tracks success/failure rates

## Performance

### Optimization Tips

1. **Adjust Workers**: Increase `--workers` for faster processing (but be respectful)
2. **Headless Mode**: Use `--headless` (default) for better performance
3. **Request Delay**: Increase `request_delay` to reduce server load
4. **Image Limits**: Adjust `max_images_per_model` to control download volume

### Benchmarks

- Typical speed: ~30-60 models per hour (depends on images)
- Image download: ~2-5 seconds per model
- Profile scraping: ~3-5 seconds per model

## Troubleshooting

### Common Issues

**ChromeDriver not found**
```bash
# webdriver-manager handles this automatically, but if issues persist:
pip install --upgrade webdriver-manager
```

**Timeout errors**
```yaml
# Increase timeout in config:
timeout: 60
```

**No models found**
```bash
# Try visible mode to debug:
python apm_models_scraper_enhanced.py --visible --test

# Try specific division:
python apm_models_scraper_enhanced.py --index-url https://apmmodels.com/w/models/dev
```

**Rate limiting**
```yaml
# Increase delay between requests:
request_delay: 3.0
```

## Best Practices

1. **Start with Test Mode**: Always test with `--test` first
2. **Respect Servers**: Use appropriate delays between requests
3. **Monitor Logs**: Check logs regularly for issues
4. **Backup Data**: Keep backups of scraped data
5. **Stay Updated**: Check for selector changes if scraping fails

## Legal & Ethical Considerations

- **Robots.txt**: Respect the site's robots.txt file
- **Terms of Service**: Review and comply with apmmodels.com terms
- **Rate Limiting**: Use reasonable delays to avoid overwhelming servers
- **Personal Use**: This scraper is intended for personal, educational use
- **Copyright**: Respect copyright and intellectual property rights

## Development

### Extending the Scraper

The scraper is modular and can be extended:

```python
from apm_models_scraper_enhanced import APMModelsEnhancedScraper

# Custom scraper
class MyCustomScraper(APMModelsEnhancedScraper):
    def _extract_custom_data(self, soup):
        # Add custom extraction logic
        pass
```

### Testing

```bash
# Run with debug output
python apm_models_scraper_enhanced.py --test --visible

# Check log file
tail -f apm_scraper_enhanced.log
```

## Contributing

Contributions are welcome! Areas for improvement:

- Additional selectors for different page layouts
- Better parallel processing with separate WebDriver instances
- Support for additional data fields
- Performance optimizations
- Better error recovery strategies

## License

This project is provided as-is for educational purposes. Users are responsible for ensuring compliance with applicable terms of service and regulations.

## Support

For issues, questions, or suggestions:
1. Check the log file: `apm_scraper_enhanced.log`
2. Review the debug HTML files created during scraping
3. Try running with `--visible --test` to observe browser behavior
4. Verify Chrome and ChromeDriver compatibility

## Version History

- **v1.0**: Initial release with three-stage pipeline
- Enhanced selectors and robust error handling
- YAML configuration support
- Comprehensive logging and validation

---

**Happy Scraping! 🎉**