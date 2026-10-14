import type { Config } from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';
import { themes as prismThemes } from 'prism-react-renderer';

const githubRepo = 'https://github.com/QY-NineClaw/NineClaw-Docs';
// Docusaurus 会自动追加 guide/、api/、manual/ 等目录，这里只写到仓库根路径
const githubEditBase = `${githubRepo}/tree/main/`;

function normalizeProxyPrefix(value: string): string {
  return value.replace(/\/+$/, '');
}

const apiProxyPrefixes = {
  nineclawManager: normalizeProxyPrefix(
    process.env.NINECLAW_MANAGER_PROXY_PREFIX ?? 'http://localhost:8510',
  ),
  nineclawWebsearch: normalizeProxyPrefix(
    process.env.NINECLAW_WEBSEARCH_PROXY_PREFIX ?? 'http://localhost:8510/ws-api',
  ),
  hermesGateway: normalizeProxyPrefix(
    process.env.HERMES_GATEWAY_PROXY_PREFIX ??
    'http://localhost:8510/traefik/nineclaw-gateway/84d07aeed0844abf',
  ),
  hermesDashboard: normalizeProxyPrefix(
    process.env.HERMES_DASHBOARD_PROXY_PREFIX ??
    'http://localhost:8510/traefik/nineclaw-dashboard/84d07aeed0844abf',
  ),
  hermesWebui: normalizeProxyPrefix(
    process.env.HERMES_WEBUI_PROXY_PREFIX ??
    'http://localhost:8510/traefik/nineclaw/a78d0479a98e417b/webui/',
  ),
  qyRag: normalizeProxyPrefix(
    process.env.QY_RAG_PROXY_PREFIX ??
    'http://localhost:8510/traefik/nineclaw-rag/84d07aeed0844abf',
  ),
};

const config: Config = {
  title: 'NineClaw',
  tagline: 'NineClaw 生态文档',
  favicon: 'img/favicon.ico',

  url: 'https://your-docusaurus-site.example.com',
  baseUrl: '/docs/',
  trailingSlash: false,

  organizationName: 'QY-NineClaw',
  projectName: 'NineClaw-Docs',

  onBrokenLinks: 'throw',
  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'warn',
      onBrokenMarkdownImages: 'warn',
    },
  },

  i18n: {
    defaultLocale: 'zh-CN',
    locales: ['zh-CN'],
  },

  presets: [
    [
      'classic',
      {
        // 「文档」部分：简介、架构、核心功能、配置
        docs: {
          id: 'guide',
          path: 'guide',
          routeBasePath: 'guide',
          sidebarPath: './sidebars-guide.ts',
          editUrl: githubEditBase,
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  plugins: [
    // 「API」部分：所有 API 参考文档
    [
      '@docusaurus/plugin-content-docs',
      {
        id: 'api',
        path: 'api',
        routeBasePath: 'api',
        sidebarPath: './sidebars-api.ts',
        editUrl: githubEditBase,
      },
    ],
    // 「手册」部分：独立的手册文档
    [
      '@docusaurus/plugin-content-docs',
      {
        id: 'manual',
        path: 'manual',
        routeBasePath: 'manual',
        sidebarPath: './sidebars-manual.ts',
        editUrl: githubEditBase,
      },
    ],
  ],

  customFields: {
    apiProxyPrefixes,
  },

  themeConfig: {
    navbar: {
      title: 'NineClaw',
      logo: {
        alt: 'NineClaw Logo',
        src: 'img/logo-small.jpg',
        style: { height: '36px' },
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'guideSidebar',
          docsPluginId: 'guide',
          position: 'left',
          label: '开发文档',
        },
        {
          type: 'docSidebar',
          sidebarId: 'apiSidebar',
          docsPluginId: 'api',
          position: 'left',
          label: 'API',
        },
        {
          type: 'docSidebar',
          sidebarId: 'manualSidebar',
          docsPluginId: 'manual',
          position: 'left',
          label: '用户手册',
        },
        {
          href: githubRepo,
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: '文档',
          items: [
            { label: '总览', to: '/guide/intro' },
            { label: 'Traefik 路由', to: '/guide/architecture/routing' },
          ],
        },
        {
          title: 'API',
          items: [
            { label: '概览', to: '/api/intro' },
            { label: 'Hermes Gateway', to: '/api/hermes-gateway' },
            { label: 'Hermes Dashboard', to: '/api/hermes-dashboard' },
            { label: 'Hermes WebUI', to: '/api/hermes-webui' },
          ],
        },
        {
          title: '用户手册',
          items: [
            { label: '概览', to: '/manual/intro' },
            { label: '系统部署', to: '/manual/system-deployment' },
            { label: '知识库', to: '/manual/knowledge' },
            { label: 'Skills', to: '/manual/skills' },
            { label: 'Models管理', to: '/manual/models' },
          ],
        },
        {
          title: '更多',
          items: [
            {
              label: 'GitHub',
              href: githubRepo,
            },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} NineClaw. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'json', 'yaml', 'docker'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
