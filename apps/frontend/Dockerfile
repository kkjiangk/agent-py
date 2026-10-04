FROM node:22-alpine AS build

WORKDIR /workspace
COPY package.json package-lock.json ./
COPY packages/api-contracts/package.json packages/api-contracts/package.json
COPY apps/frontend/package.json apps/frontend/package.json
RUN npm ci

COPY packages/api-contracts packages/api-contracts
COPY apps/frontend apps/frontend
COPY config/project.template.json config/project.template.json
COPY config/user.project.template.json config/user.project.template.json
RUN npm run frontend:build

FROM nginx:1.29-alpine
COPY apps/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/apps/frontend/dist /usr/share/nginx/html
EXPOSE 80

