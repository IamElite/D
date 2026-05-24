FROM elitemind/wzmlxdz:main

WORKDIR /usr/src/app

COPY requirements.txt .

RUN .venv/bin/pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x start.sh || true

CMD ["bash", "start.sh"]
