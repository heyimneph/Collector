# Collector

## Running with Docker

Build the Docker image:

```sh
docker build -t collector .
```

Run the bot container (make sure `DISCORD_TOKEN` is set):

```sh
docker run --env DISCORD_TOKEN=your_token collector
```
=======
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

