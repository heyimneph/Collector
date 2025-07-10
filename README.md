# Collector

## Setup

Install dependencies using the provided `requirements.txt` file:

```bash
pip install -r requirements.txt
```

### Docker

The included `Dockerfile` copies `requirements.txt` and installs these packages during build:

```bash
docker build -t collector-bot .
```

