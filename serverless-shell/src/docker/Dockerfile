FROM ubuntu:22.04

# Install necessary CLI tools
RUN apt-get update && apt-get install -y \
    curl \
    git \
    jq \
    vim \
    iputils-ping \
    python3 \
    python3-pip \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN useradd -m shelluser
USER shelluser
WORKDIR /home/shelluser

# Keep the container running indefinitely so we can exec into it
CMD ["tail", "-f", "/dev/null"]