import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Режим A: vite dev → проксируем на продакшн GeoServer (read-only, данные 2024)
      // Для режима B (локальный docker-compose) этот блок не используется — там nginx
      '/geoserver': {
        target: 'http://geobotany.xyz',
        changeOrigin: true,
      },
    },
  },
});

