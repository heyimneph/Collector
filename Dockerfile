# Use an official Python runtime as a parent image
FROM python:3.12-slim-bullseye

# Set the working directory to /app
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Copy the entry point script
COPY entrypoint.sh /entrypoint.sh

# Make the entry point script executable
RUN chmod +x /entrypoint.sh

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Ensure the directories are created
RUN mkdir -p /app/data/databases \
    && mkdir -p /app/data/logs


# Use the entry point script to start the container
ENTRYPOINT ["/entrypoint.sh"]
