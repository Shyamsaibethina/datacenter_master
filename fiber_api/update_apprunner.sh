AWS_REGION=us-east-1                                         
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REPO=fiber-api                                                        
TAG=v65
IMAGE=${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${REPO}:${TAG}
SERVICE_ARN=arn:aws:apprunner:us-east-1:471112714165:service/BroadBandAPI/1a4ff0d8aa334cfc88b3965174a3e315

aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin ${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com                      
docker buildx create --use || true
docker buildx build --platform linux/amd64 -t ${IMAGE} --push .
  \aws apprunner update-service --service-arn "$SERVICE_ARN" \
  --source-configuration "ImageRepository={ImageIdentifier=${IMAGE},ImageRepositoryType=ECR,ImageConfiguration={Port=8080}}"