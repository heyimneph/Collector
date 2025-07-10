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
