- Vue官方文档：https://cn.vuejs.org/guide/introduction.html
- Vite官方文档：https://vitejs.cn/vite3-cn/guide/

### 一、Vue 是什么 & 前端运行环境

- Vue 就是运行在浏览器里的“模板引擎 + 状态管理器”，负责把数据渲染成 HTML 并处理用户交互。
- 单页应用（SPA）概念：只有一个 HTML 文件，路由跳转由 JS 模拟，不再从服务端下载新页面。

---

### 二、创建项目 & 目录结构

**直接现场演示**：

```bash
npm create vue@latest          # 选 TypeScript, Vue Router, Pinia
cd vue-project && npm install
npm run dev
```

**对照后端讲解目录**：

```
src/
  views/        → 页面组件，相当于 Controller 返回的视图
  components/   → 可复用组件，类似工具类/Service
  router/       → 前端路由配置，相当于 Controller层
  stores/       → 状态管理 (Pinia)，类似 Redis/缓存
  api/          → 封装后端请求
```

---

### 三、Vue 核心概念：响应式 + 模板

**1. 响应式数据（reactive/ref）**

- 类比：后端修改变量值后，需要手动再把新值塞回 ModelAndView；Vue 的响应式数据一旦改变，所有绑定的视图**自动更新**。
- 代码演示：
  ```ts
  import { ref } from 'vue';
  const count = ref(0); // 创建一个响应式基础变量
  const user = reactive({
    // 响应式对象
    name: 'Alice',
    role: 'admin',
  });
  ```
- 在模板中使用：`{{ count }}`，修改：`count.value++`（**注意 .value**）

**2. 模板语法速览**

- 插值 `{{ }}` 只能写表达式，不能写语句。
- 条件渲染：`v-if="isShow"` / `v-show`
- 列表渲染：`v-for="item in list" :key="item.id"`（必须绑定 key，类似数据库主键）
- 事件绑定：`@click="handleClick"`，相当于后端的 `onClick` 监听
- 属性绑定：` :src="imgUrl"`，动态属性

---

### 四、组件化与组件通信

**1. 组件 = 页面的一部分**

- 一个 `.vue` 文件就是一个组件，包含三块：
  ```vue
  <script setup lang="ts">
  // 逻辑（像 Controller 方法）
  import { ref } from 'vue';
  const title = ref('用户列表');
  </script>
  <template>
    // 视图（HTML）
    <h1>{{ title }}</h1>
  </template>
  <style scoped>
  // 局部样式（类似私有方法）
  </style>
  ```

**2. Props 向下，Events 向上（父传子，子通知父）**

- **Props**：父组件传给子组件的数据，相当于后端的方法参数。
  ```ts
  // 子组件定义
  const props = defineProps<{ users: User[] }>();
  ```
- **Emits**：子组件通知父组件发生了什么事，类似回调函数或事件发布。
  ```ts
  const emit = defineEmits<{ (e: 'delete', id: number): void }>();
  ```
- 单向数据流：数据只能从父到子，子不能直接修改 props，必须通过 emit 通知父组件修改。这类似后端分层中，DAO 不能直接修改 Service 的状态。

**3. 插槽（slot）**：父组件把一段 HTML 传给子组件显示，就像后端注入一段片段。

---

### 五、路由与页面切换

- **配置路由**：`router/index.ts` 像 Spring MVC 的 `@RequestMapping`。
  ```ts
  const routes = [
    { path: '/users', component: () => import('@/views/UserList.vue') },
    { path: '/users/:id', component: () => import('@/views/UserDetail.vue') },
  ];
  ```
- 页面跳转：用 `<router-link to="/users">` 或编程式
  `router.push('/users')`，等价于后端重定向。
- **路由守卫**：权限控制，类似拦截器。例如在 `beforeEach` 里检查 token：
  ```ts
  router.beforeEach((to, from) => {
    if (to.meta.requiresAuth && !token) return '/login';
  });
  ```

---

### 六、状态管理 Pinia

**什么时候用**：多个页面或组件共享同一份数据时（如当前用户信息、全局配置），避免层层传递 props。

- **定义 Store**（类似一个 Service 单例）：
  ```ts
  export const useUserStore = defineStore('user', () => {
    const user = ref<User | null>(null)
    async function fetchLogin() { ... }
    return { user, fetchLogin }
  })
  ```
- 在组件中直接使用：`const userStore = useUserStore(); userStore.user`
- **对比后端**：就是前端运行时的一个缓存层，既可以存数据，也可以封装业务逻辑（请求、更新）。不同于后端数据库，刷新页面就没了。

---

### 七、对接后端 API

**1. Axios 封装（像封装 HttpClient）**

```ts
// api/request.ts
import axios from 'axios'
const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 10000
})
// 请求拦截器：自动带 Token
request.interceptors.request.use(config => {
  config.headers.Authorization = `Bearer ${getToken()}`
  return config
})
// 响应拦截器：统一解包 code/data/message
request.interceptors.response.use(res => res.data, err => { ... })
```

**2. API 层组织**

```ts
// api/user.ts
export const getUserList = (params: PageParams) =>
  request.get('/api/users', { params });
export const createUser = (data: UserForm) => request.post('/api/users', data);
```

- **类型约束**：利用 TypeScript 定义请求和响应的接口，形成前后端契约。

**3. 解决跨域**：在 `vite.config.ts`
配置 proxy（开发环境），如同 Nginx 反向代理，不再需要后端手动加 CORS。

---

### 八、样式处理与 UI 库

**风格**：后端人员无需深研 CSS，直接引入 UI 库。

- **安装 Element Plus**：`npm install element-plus`
- 全局注册后，直接使用预置组件：
  ```vue
  <el-table :data="userList" border>
  <el-button @click="handleAdd">新增</el-button>
  ```
- 布局用简单的 Flex/Grid，AI一句话就能生成：“用 flex 让这两个按钮左右分开”。
- 需要定制样式时，使用 `<style scoped>` + CSS 变量，不污染全局。

---

### 九、构建打包与部署

- `npm run dev` → 启动本地开发服务器，支持热更新（改代码浏览器自动刷新）。
- `npm run build` → 产出 `dist` 目录，里面是纯静态文件（HTML + JS +
  CSS），相当于用 Maven/Gradle 打出 jar 包。
- 部署：把 `dist` 扔到 Nginx 的 html 目录，配置 `try_files`
  解决 history 路由刷新 404。
  ```shell
  location /document  {
    proxy_read_timeout 60s;
    proxy_connect_timeout 60s;
    root   /data/apps/document;
    index  index.html;
    try_files $uri $uri/ /index.html;
    add_header Cache-Control no-cache;
  }
  ```
- 环境变量：`.env.production` 中设置
  `VITE_API_BASE_URL`，构建时注入，运行时无法更改（这点和后端配置文件不同，需注意）。

---

### 十、用 AI 辅助写

- **根据需求生成组件**：“用 Vue3 + TypeScript + Element
  Plus 写一个带分页和搜索的用户表格。”
- **对接 API**：“后端接口是 GET /api/users?page=1&size=10，返回 {code, data: {
  list, total }}，请生成前端 API 封装和调用代码。”
- **报错修复**：把终端或浏览器控制台的报错直接复制给 AI，解释原因并给出修改方案。
- **样式调整**：“怎么让这个表单弹窗在移动端也全屏显示？”

---
