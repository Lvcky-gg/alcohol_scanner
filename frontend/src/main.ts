import { createApp } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import Aura from '@primeuix/themes/aura'
import '@fontsource/rajdhani/500.css'
import '@fontsource/rajdhani/700.css'
import '@fontsource/share-tech-mono/400.css'
import 'primeicons/primeicons.css'
import './style.css'
import App from './App.vue'

const app = createApp(App)

app.use(createPinia())
app.use(PrimeVue, {
	theme: {
		preset: Aura,
	},
})

app.mount('#app')
