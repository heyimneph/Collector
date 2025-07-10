# Collector

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

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


