import { defineConfig } from 'vite'
import mkcert from 'vite-plugin-mkcert'

// En modo https se genera un certificado local para poder abrirlo desde el visor
// dentro de la misma red. Para la demo real conviene desplegar a Netlify.
export default defineConfig(({ mode }) => ({
  plugins: mode === 'https' ? [mkcert()] : [],
  server: { port: 5173, strictPort: false },
  build: { target: 'es2020', chunkSizeWarningLimit: 2000 },
}))
