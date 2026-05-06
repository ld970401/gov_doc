/**
 * 自托管 TinyMCE：在应用入口之前执行，使 tinymce-vue 检测到 window.tinymce，避免走 CDN。
 */
import tinymce from 'tinymce/tinymce';
import 'tinymce/themes/silver/theme';
import 'tinymce/icons/default/icons';
import 'tinymce/models/dom/model';
/** 社区中文语言包（npm 本地包，非外链） */
import 'tinymce-i18n/langs7/zh_CN.js';

/** 与原型稿一致的少量文案覆盖 */
tinymce.addI18n('zh_CN', {
  Bold: 'B 加粗',
  'Bullet list': '列表',
  'Numbered list': '编号',
});
