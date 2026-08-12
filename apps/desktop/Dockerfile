FROM node:22-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

RUN npm run build

FROM node:22-alpine AS runner

WORKDIR /app
COPY --from=builder /app ./

EXPOSE 5409

ENV PORT=5409
ENV HOST=0.0.0.0

CMD ["npm", "run", "preview"]
