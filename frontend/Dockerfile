FROM node:22-alpine AS build
WORKDIR /app
ARG VITE_ENERGYPILOT_API
ENV VITE_ENERGYPILOT_API=$VITE_ENERGYPILOT_API
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx","-g","daemon off;"]
