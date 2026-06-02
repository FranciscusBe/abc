FROM python:3.11-slim
WORKDIR /app
COPY proxy.py .
RUN pip install cryptography
EXPOSE 8080
CMD ["python", "proxy.py", "--port", "8080", "--bind", "0.0.0.0"]
