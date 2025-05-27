#!/bin/bash

# MSK Docker Setup and ECR Deployment Script
echo "🚀 Setting up MSK Docker environment with ECR deployment..."

# ECR Configuration
ECR_REGISTRY="YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com"
CONSUMER_REPO="msk-consumer-service-repo"
PRODUCER_REPO="msk-producer-service-repo"
AWS_REGION="us-east-1"

# Create certs directory if it doesn't exist
mkdir -p certs

# Check if .env file exists (check both current dir and parent dir)
ENV_FILE=""
if [ -f .env ]; then
    ENV_FILE=".env"
    echo "✅ .env file found in current directory"
elif [ -f ../.env ]; then
    ENV_FILE="../.env"
    echo "✅ .env file found in parent directory"
else
    echo "❌ .env file not found in current or parent directory."
    echo "📝 Example .env file content needed:"
    echo "AWS_DEFAULT_REGION=us-east-1"
    echo "MSK_BROKERS=your-broker-endpoints"
    echo "MSK_TOPIC=your-topic"
    echo "# ... other config variables"
    exit 1
fi

# Download Amazon Root CA1 certificate if not exists
if [ ! -f certs/AmazonRootCA1.pem ]; then
    echo "📥 Downloading Amazon Root CA1 certificate..."
    curl -o certs/AmazonRootCA1.pem https://www.amazontrust.com/repository/AmazonRootCA1.pem
    echo "✅ Certificate downloaded"
else
    echo "✅ Certificate already exists"
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

# Check if AWS CLI is available
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI is not installed. Please install AWS CLI and try again."
    exit 1
fi

# Check if required files exist
required_files=("consumer_service.py" "producer_service.py" "requirements.txt" "sample_messages.json" "Dockerfile.consumer" "Dockerfile.producer")
for file in "${required_files[@]}"; do
    if [ ! -f "$file" ]; then
        echo "❌ Required file '$file' not found. Please ensure all files are in the current directory."
        exit 1
    fi
done

echo "🔐 Logging into ECR..."
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_REGISTRY
if [ $? -ne 0 ]; then
    echo "❌ ECR login failed. Please check your AWS credentials and try again."
    exit 1
fi
echo "✅ ECR login successful"

# Generate dynamic version tag
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
GIT_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "local")
VERSION_TAG="v${TIMESTAMP}-${GIT_HASH}"

echo "🏷️  Using version tag: $VERSION_TAG"

echo "🏗️  Building and pushing Consumer service..."
docker build -f Dockerfile.consumer -t msk-consumer-service .
if [ $? -ne 0 ]; then
    echo "❌ Consumer build failed"
    exit 1
fi

docker tag msk-consumer-service:latest $ECR_REGISTRY/$CONSUMER_REPO:latest
docker tag msk-consumer-service:latest $ECR_REGISTRY/$CONSUMER_REPO:$VERSION_TAG

echo "📤 Pushing Consumer to ECR..."
docker push $ECR_REGISTRY/$CONSUMER_REPO:latest
docker push $ECR_REGISTRY/$CONSUMER_REPO:$VERSION_TAG
if [ $? -ne 0 ]; then
    echo "❌ Consumer push failed"
    exit 1
fi
echo "✅ Consumer service pushed successfully"

echo "🏗️  Building and pushing Producer service..."
docker build -f Dockerfile.producer -t msk-producer-service .
if [ $? -ne 0 ]; then
    echo "❌ Producer build failed"
    exit 1
fi

docker tag msk-producer-service:latest $ECR_REGISTRY/$PRODUCER_REPO:latest
docker tag msk-producer-service:latest $ECR_REGISTRY/$PRODUCER_REPO:$VERSION_TAG

echo "📤 Pushing Producer to ECR..."
docker push $ECR_REGISTRY/$PRODUCER_REPO:latest
docker push $ECR_REGISTRY/$PRODUCER_REPO:$VERSION_TAG
if [ $? -ne 0 ]; then
    echo "❌ Producer push failed"
    exit 1
fi
echo "✅ Producer service pushed successfully"

echo "🎯 Setup and ECR deployment complete!"
echo ""
echo "📦 Docker images pushed to ECR:"
echo "  Consumer: $ECR_REGISTRY/$CONSUMER_REPO:latest"
echo "  Consumer: $ECR_REGISTRY/$CONSUMER_REPO:$VERSION_TAG"
echo "  Producer: $ECR_REGISTRY/$PRODUCER_REPO:latest"
echo "  Producer: $ECR_REGISTRY/$PRODUCER_REPO:$VERSION_TAG"
echo ""
echo "🚀 To run containers directly from ECR:"
echo "  docker run --env-file $ENV_FILE $ECR_REGISTRY/$CONSUMER_REPO:latest"
echo "  docker run --env-file $ENV_FILE $ECR_REGISTRY/$PRODUCER_REPO:latest"
echo ""
echo "🏷️  Or use specific version:"
echo "  docker run --env-file $ENV_FILE $ECR_REGISTRY/$CONSUMER_REPO:$VERSION_TAG"
echo "  docker run --env-file $ENV_FILE $ECR_REGISTRY/$PRODUCER_REPO:$VERSION_TAG"
echo ""
echo "📁 Project files created in: $(pwd)"
echo "🎉 ECR deployment complete!"