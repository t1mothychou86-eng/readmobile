import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';
import { VitePWA } from 'vite-plugin-pwa';
export default defineConfig({
  base: './',
  plugins: [preact(), VitePWA({
    registerType: 'autoUpdate',
    includeAssets: ['apple-touch-icon.png'],
    manifest: {
      name: 'PaperCart 文献购物车', short_name: 'PaperCart', lang: 'zh-CN',
      description: '碎片时间读文献，一键加入 Zotero', theme_color: '#24624b', background_color: '#f5f5ef',
      display: 'standalone', start_url: './', scope: './',
      icons: [
        { src: 'icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
        { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
      ],
    },
    workbox: {
      globPatterns: ['**/*.{js,css,html,png,svg,woff2}'],
      globIgnores: ['**/data/**'],
      runtimeCaching: [{
        urlPattern: ({ url, sameOrigin }) => sameOrigin && url.pathname.endsWith('/data/feed.json'),
        handler: 'NetworkFirst', options: { cacheName: 'papercart-feed-v1', networkTimeoutSeconds: 8,
          cacheableResponse: { statuses: [200] }, expiration: { maxEntries: 1 },
          plugins: [{ fetchDidSucceed: async ({ response }) => {
            if (!response.ok) throw new Error('Feed network response failed');
            return response;
          } }] },
      }],
      navigateFallbackDenylist: [/\/data\//],
    },
  })],
});
