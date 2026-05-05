# =============================================================================
# Frontend image — Vite dev server
# Production build is out of scope for the hackathon dev loop. We only ship
# `npm run dev`, mounted to the host source via docker-compose.
# =============================================================================
FROM node:20-alpine

WORKDIR /app

# Install deps in a cached layer; the source is bind-mounted at runtime.
COPY package*.json ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
