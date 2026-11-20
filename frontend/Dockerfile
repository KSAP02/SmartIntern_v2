FROM node:lts-alpine
WORKDIR /app
COPY package.json ./
RUN npm install
COPY tsconfig.json tsconfig.web.json vite.config.ts ./
COPY src ./src
COPY web ./web
RUN npm run build
EXPOSE 3000
CMD ["node", "dist/server.js"]
