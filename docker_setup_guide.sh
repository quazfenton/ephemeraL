#!/bin/bash
# Docker Setup Guide for Different Environments

echo "Docker Installation Guide"
echo "========================="

# Detect the OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$NAME
    VER=$VERSION_ID
else
    OS=$(uname -s)
fi

echo "Detected OS: $OS"

if [[ "$OS" == *"Ubuntu"* ]]; then
    echo "Setting up Docker for Ubuntu..."
    
    # Update the apt package index
    sudo apt update
    
    # Install packages to allow apt to use a repository over HTTPS
    sudo apt install -y \
        ca-certificates \
        curl \
        gnupg \
        lsb-release
    
    # Add Docker's official GPG key
    sudo mkdir -p /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc

    # Set up the repository
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$UBUNTU_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

elif [[ "$OS" == *"Debian"* ]]; then
    echo "Setting up Docker for Debian..."

    # Update the apt package index
    sudo apt update
    
    # Install packages to allow apt to use a repository over HTTPS
    sudo apt install -y \
        ca-certificates \
        curl \
        gnupg \
        lsb-release
    
    # Add Docker's official GPG key
    sudo mkdir -p /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc

    # Set up the repository
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

else
    echo "Unsupported OS: $OS"
    echo "Please visit https://docs.docker.com/engine/install/ for manual installation instructions."
    exit 1
fi

# Update the apt package index again
sudo apt update

# Install Docker Engine, containerd, and Docker Compose
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Post-installation steps for Linux
echo "Configuring Docker for non-root access..."
sudo groupadd docker 2>/dev/null || true
sudo usermod -aG docker $USER

echo ""
echo "Installation complete!"
echo ""
echo "Note: If you're in a containerized environment (like Docker-in-Docker, or cloud platforms),"
echo "the Docker daemon may need to be started differently or may already be running."
echo ""
echo "To test Docker, you can run:"
echo "  docker run hello-world"
echo ""
echo "If you get permission errors, you may need to run:"
echo "  sudo usermod -aG docker $USER"
echo "Then log out and log back in for the changes to take effect."