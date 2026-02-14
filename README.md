# OPML2JSON

A Flask-based web service that converts OPML (Outline Processor Markup Language) files to JSON and aggregates RSS feed items with pagination support.

## Features

- **OPML Parsing**: Upload OPML files or provide URLs to OPML documents
- **RSS Aggregation**: Automatically fetches and aggregates items from all RSS feeds listed in the OPML
- **Smart Caching**: Implements 1-hour caching for RSS feeds to improve performance
- **Pagination**: Cursor-based pagination for efficient browsing of large feed collections
- **CORS Support**: Cross-Origin Resource Sharing enabled for frontend integration
- **Full Content Extraction**: Retrieves full article content, summaries, and audio enclosures

## API Endpoints

### POST `/upload_opml`

Accepts OPML file uploads or URLs and returns paginated JSON feed items.

**Parameters:**
- `file` (file): OPML file upload
- `url` (string): URL to an OPML file
- `cursor` (float, optional): Timestamp cursor for pagination
- `limit` (int, optional): Number of items per page (default: 20)

**Response:**
```json
{
  "items": [
    {
      "title": "Article Title",
      "link": "https://example.com/article",
      "published": "Mon, 01 Jan 2024 12:00:00 GMT",
      "summary": "Article summary...",
      "full_content": "Full article content...",
      "source": "Feed Title",
      "author": "Author Name",
      "audio": ["https://example.com/podcast.mp3"]
    }
  ],
  "next_cursor": 1234567890.0,
  "title": "OPML Feed Title"
}
```

### GET `/`

Simple HTML form for testing the service.

## Installation

### Using Docker (Recommended)

1. Clone the repository:
```bash
git clone https://github.com/yourusername/opml2json.git
cd opml2json
```

2. Build and run with Docker Compose:
```bash
docker compose build
docker compose up -d
```

The service will be available at `http://localhost:8000`

### Manual Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the application:
```bash
# Development
python hello.py

# Production with Gunicorn
gunicorn --bind 0.0.0.0:8000 --workers 4 hello:app
```

## Dependencies

- Flask - Web framework
- feedparser - RSS/Atom feed parsing
- listparser - OPML parsing
- requests - HTTP library
- flask-cors - CORS support
- gunicorn - WSGI HTTP server

## Deployment

This application is designed to run as a containerized service behind a reverse proxy (e.g., Caddy, nginx).

Example Caddyfile configuration:
```caddyfile
opml2json.example.com {
  handle /.well-known/acme-challenge/* {
    root * /srv/www/opml2json.example.com
    file_server
  }

  handle {
    reverse_proxy opml2json:8000
  }
}
```

## Use Cases

- Aggregate multiple RSS feeds into a single stream
- Convert OPML subscription lists to JSON for web applications
- Build custom RSS readers with pagination support
- Extract and cache content from multiple sources

## License

See LICENSE file for details.

## Author

Stephen Downes - stephen@downes.ca
