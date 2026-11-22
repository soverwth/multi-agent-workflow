import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // 可选的独立 Vite 热更新模式：前端仍通过相对地址访问 API，
  // 开发服务器把请求转发到 B02 的唯一后端端口。
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:7100',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:7100',
        ws: true,
      },
    },
  },
})
