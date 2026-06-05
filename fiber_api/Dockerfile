# Fast, small image 
FROM python:3.11-slim 

# System deps (certs, curl for health checks) 
RUN apt-get update && apt-get install -y --no-install-recommends \ 
    ca-certificates curl && \ 
    rm -rf /var/lib/apt/lists/* 

# App code 
WORKDIR /app 
COPY requirements.txt /app/ 
RUN pip install --no-cache-dir -r requirements.txt 
COPY . /app 
EXPOSE 8080 
ENV PYTHONUNBUFFERED=1 

#Add debug logs so App Runner shows full tracebacks 
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "debug"]