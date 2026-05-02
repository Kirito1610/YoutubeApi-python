FROM node:20

RUN apt-get update && apt-get install -y python3 python3-pip
RUN pip install yt-dlp

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

CMD ["npm","start"]