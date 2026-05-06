import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
/** TinyMCE 自托管：注册 window.tinymce，避免 tinymce-vue 回退到 CDN */
import '@/components/rich-text/tinymce/boot'
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles/index.scss'

import '@/permission'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(ElementPlus)
app.use(router)

app.mount('#app')
