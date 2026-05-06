/** 公文预览区视觉一致的编辑区样式（写入 TinyMCE iframe） */
export const DOC_CONTENT_STYLE = `
  body {
    font-family: 'FangSong_GB2312', '仿宋_GB2312', 'STFangsong', FangSong, 'Noto Serif SC', serif;
    font-size: 16pt;
    line-height: 1.8;
    color: #1e293b;
    margin: 16px;
    max-width: 100%;
    box-sizing: border-box;
  }
  .doc-red-header {
    display: grid;
    grid-template-columns: 1fr auto max-content;
    align-items: center;
    column-gap: 12px;
    margin: 0;
    padding: 16px 0 10px;
    border-bottom: 2px solid #dc2626;
  }
  .doc-org {
    grid-column: 2;
    justify-self: center;
    text-align: center;
    font-size: 16pt;
    font-weight: 700;
    color: #dc2626;
  }
  .doc-issue-no {
    grid-column: 3;
    justify-self: end;
    text-align: right;
    font-size: 14pt;
    font-weight: 600;
    color: #dc2626;
  }
  .doc-main-title {
    font-size: 20pt;
    font-weight: 700;
    text-align: center;
    margin: 16px 0;
    line-height: 1.4;
    color: #1e293b;
  }
  .doc-recipients {
    font-size: 14pt;
    font-weight: 600;
    margin: 0 0 16px;
    color: #1e293b;
  }
  .doc-body p {
    margin: 0 0 12px;
    text-indent: 2em;
    font-size: 14pt;
    line-height: 1.8;
    color: #1e293b;
  }
  .doc-body h4 {
    font-size: 15pt;
    font-weight: 600;
    margin: 16px 0 8px;
    text-indent: 0;
    color: #1e293b;
  }
  .doc-body .sub-p {
    text-indent: 2em;
  }
  .doc-footer {
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid #e2e8f0;
    text-align: right;
    font-size: 14pt;
    color: #1e293b;
  }
  .doc-footer p {
    margin: 0;
    line-height: 1.8;
  }
`;

/** 右侧联动编辑器内「纸张」区：更大页边距、正文色贴近设计稿 */
export const DOC_CONTENT_STYLE_PANEL = `
  body {
    font-family: 'FangSong_GB2312', '仿宋_GB2312', 'STFangsong', FangSong, 'Noto Serif SC', serif;
    font-size: 16pt;
    line-height: 1.75;
    color: #262626;
    margin: 40px 40px 36px;
    max-width: 100%;
    box-sizing: border-box;
    background: #ffffff;
  }
  .doc-red-header {
    display: grid;
    grid-template-columns: 1fr auto max-content;
    align-items: center;
    column-gap: 12px;
    margin: 0;
    padding: 16px 0 10px;
    border-bottom: 2px solid #dc2626;
  }
  .doc-org {
    grid-column: 2;
    justify-self: center;
    text-align: center;
    font-size: 16pt;
    font-weight: 700;
    color: #dc2626;
  }
  .doc-issue-no {
    grid-column: 3;
    justify-self: end;
    text-align: right;
    font-size: 14pt;
    font-weight: 600;
    color: #dc2626;
  }
  .doc-main-title {
    font-size: 20pt;
    font-weight: 700;
    text-align: center;
    margin: 20px 0 16px;
    line-height: 1.45;
    color: #262626;
  }
  .doc-recipients {
    font-size: 14pt;
    font-weight: 600;
    margin: 0 0 16px;
    color: #262626;
  }
  .doc-body p {
    margin: 0 0 12px;
    text-indent: 2em;
    font-size: 14pt;
    line-height: 1.75;
    color: #262626;
  }
  .doc-body h4 {
    font-size: 15pt;
    font-weight: 600;
    margin: 16px 0 8px;
    text-indent: 0;
    color: #262626;
  }
  .doc-body .sub-p {
    text-indent: 2em;
  }
  .doc-footer {
    margin-top: 20px;
    padding-top: 16px;
    border-top: 1px solid #f0f0f0;
    text-align: right;
    font-size: 14pt;
    color: #262626;
  }
  .doc-footer p {
    margin: 0;
    line-height: 1.75;
  }
`;

export function getTinymceBaseUrl(): string {
  const base = import.meta.env.BASE_URL || '/';
  return base.endsWith('/') ? `${base}tinymce` : `${base}/tinymce`;
}

export function createDocEditorInit(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    license_key: 'gpl',
    promotion: false,
    branding: false,
    language: 'zh_CN',
    toolbar_mode: 'wrap',
    base_url: getTinymceBaseUrl(),
    suffix: '.min',
    plugins: 'lists autoresize link',
    toolbar: 'styles | bold bullist numlist | fontfamily fontsize',
    fontsize_formats: '12pt 14pt 16pt 18pt 20pt',
    font_family_formats:
      '仿宋_GB2312=FangSong_GB2312,FangSong,STFangsong,serif;宋体=SimSun,serif;黑体=SimHei,sans-serif;楷体=KaiTi,serif;微软雅黑=Microsoft YaHei,sans-serif',
    style_formats: [
      { title: '正文', block: 'p', format: 'p' },
      { title: '标题', block: 'h2', format: 'h2' },
      { title: '引用', block: 'blockquote', format: 'blockquote' },
    ],
    style_formats_merge: false,
    menubar: false,
    statusbar: true,
    min_height: 280,
    autoresize_bottom_margin: 16,
    resize: true,
    content_style: DOC_CONTENT_STYLE,
    contextmenu: false,
    ...overrides,
  };
}
