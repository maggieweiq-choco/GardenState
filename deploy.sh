#!/bin/bash

# Cloud Run Deployment Script for Garden Agent
# Usage: ./deploy.sh [project-id] [region] [service-name]

PROJECT_ID=${1:-"your-project-id"}
REGION=${2:-"us-central1"}
SERVICE_NAME=${3:-"garden-agent"}

echo "📦 Deploying Garden Agent to Cloud Run"
echo "   Project: $PROJECT_ID"
echo "   Region: $REGION"
echo "   Service: $SERVICE_NAME"
echo ""

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "❌ gcloud CLI is not installed. Please install it first."
    exit 1
fi

# Set the project
gcloud config set project $PROJECT_ID

# Build and push the image
echo "🔨 Building Docker image..."
gcloud builds submit --tag gcr.io/$PROJECT_ID/$SERVICE_NAME

if [ $? -ne 0 ]; then
    echo "❌ Build failed"
    exit 1
fi

echo "✅ Image built and pushed successfully"
echo ""

# Deploy to Cloud Run
echo "🚀 Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
  --image gcr.io/$PROJECT_ID/$SERVICE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --memory 512Mi \
  --timeout 3600 \
  --min-instances=1 \
  --max-instances=1 \
  --set-env-vars="MDB_MCP_CONNECTION_STRING=$MDB_MCP_CONNECTION_STRING,GOOGLE_API_KEY=$GOOGLE_API_KEY${PERENUAL_API_KEY:+,PERENUAL_API_KEY=$PERENUAL_API_KEY}${GOOGLE_MAPS_API_KEY:+,GOOGLE_MAPS_API_KEY=$GOOGLE_MAPS_API_KEY}"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Deployment successful!"
    echo ""
    echo "🌐 Service URL:"
    gcloud run services describe $SERVICE_NAME --region $REGION --format='value(status.url)'
else
    echo "❌ Deployment failed"
    exit 1
fi
