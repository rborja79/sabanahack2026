import { defineConfig } from 'vite'
import mkcert from 'vite-plugin-mkcert'

// En modo https se genera un certificado local para poder abrirlo desde el visor
// dentro de la misma red. Desde el Quest es mas facil usar adb reverse: ver
// docs/quest.md.
export default defineConfig(({ mode }) => ({
  plugins: mode === 'https' ? [mkcert()] : [],
  server: { port: 5173, strictPort: false },
  // es2022 porque el emulador de visor se carga con un import de nivel superior.
  esbuild: { target: 'es2022' },
  optimizeDeps: { esbuildOptions: { target: 'es2022' } },
  build: { target: 'es2022', chunkSizeWarningLimit: 2500 },
}))
