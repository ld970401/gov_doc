// ==================== 1. 默认配置（每个元素独立） ====================
const BASE_FONT = '仿宋,FangSong,仿宋_GB2312,STFangsong,华文仿宋,serif';
const HEI_FONT = '黑体,SimHei,STHeiti,sans-serif';
const KAI_FONT = '楷体,KaiTi,STKaiti,serif';
const TITLE_FONT = '方正小标宋简体,华文楷体,宋体,serif';

const DEFAULTS = {
  title: {
    fontFamily: TITLE_FONT,
    fontSize: 22,
    lineHeight: 2,
    textAlign: 'center',
    textIndent: '0',

    fontWeight: 'normal',
  },
  receiver: {
    fontFamily: BASE_FONT,
    fontSize: 16,
    lineHeight: 2,
    textIndent: '0',
    fontWeight: 'normal',
  },
  text: {
    fontFamily: BASE_FONT,
    fontSize: 16,
    lineHeight: 2,
    textIndent: '2em',
    fontWeight: 'normal',
  },
  heading1: {
    fontFamily: HEI_FONT,
    fontSize: 16,
    lineHeight: 2,
    textIndent: '2em',
    fontWeight: 'normal',
  },
  heading2: {
    fontFamily: KAI_FONT,
    fontSize: 16,
    lineHeight: 2,
    textIndent: '2em',
    fontWeight: 'normal',
  },
  heading3: {
    fontFamily: BASE_FONT,
    fontSize: 16,
    lineHeight: 2,
    textIndent: '2em',
    fontWeight: 'normal',
  },
  heading4: {
    fontFamily: BASE_FONT,
    fontSize: 16,
    lineHeight: 2,
    textIndent: '2em',
    fontWeight: 'normal',
  },
  attachment: {
    fontFamily: BASE_FONT,
    fontSize: 16,
    lineHeight: 2,
    textIndent: '2em',
    fontWeight: 'normal',
  },
  sign: {
    fontFamily: BASE_FONT,
    fontSize: 16,
    lineHeight: 2,
    textAlign: 'right',
    paddingRight: '4em',
    textIndent: '0',
    fontWeight: 'normal',
  },
  date: {
    fontFamily: BASE_FONT,
    fontSize: 16,
    lineHeight: 2,
    textAlign: 'right',
    paddingRight: '4em',
    textIndent: '0',
    fontWeight: 'normal',
  },
};

/**
 * 仅将英文、数字、空格、英文标点符号包裹在 span 中。
 * 中文部分（含中文标点）保持纯文本，不加任何标签。
 *
 * @param text 原始文本
 * @param latinFont 西文字体配置字符串 (例如: "'Times New Roman', 'Arial'")
 */
export function wrapLatinOnly(
  text: string,
  latinFont: string = "'Times New Roman', 'Arial'"
): string {
  if (!text) return '';

  // 正则解释：
  // [^\u4e00-\u9fa5\u3000-\u303f\uff00-\uffef]+
  // 匹配连续的一个或多个字符，这些字符【不是】汉字、【不是】中文标点、【不是】全角字符。
  // 这自然包含了：英文字母、数字、半角空格、半角标点符号。
  const regex = /[^\u4e00-\u9fa5\u3000-\u303f\uff00-\uffef×]+/g;

  let result = '';
  let lastIndex = 0;

  // 使用 replace 的回调函数来定位和替换，但我们需要手动构建结果以跳过中文部分的包装
  // 这里使用 matchAll 或者手动遍历 match 结果更直观，为了兼容性使用 exec 循环
  let match;
  while ((match = regex.exec(text)) !== null) {
    const start = match.index;
    const end = start + match[0].length;
    const content = match[0];

    // 1. 添加匹配点之前的中文部分 (原样输出，不加 span)
    if (start > lastIndex) {
      const chinesePart = text.substring(lastIndex, start);
      // 中文部分只需转义 HTML 特殊字符，不需要包 span
      result += chinesePart.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // 2. 添加当前的西文部分 (包裹 span)
    const safeContent = content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    result += `<span style="font-family: ${latinFont};">${safeContent}</span>`;

    // 更新 lastIndex
    lastIndex = end;
  }

  // 3. 添加末尾剩余的中文部分 (如果有)
  if (lastIndex < text.length) {
    const remaining = text.substring(lastIndex);
    result += remaining.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  return result;
}
/**
 * 基于真实 DOM 的宽度测量，返回 pt 单位，供 `margin-right: xxpt` 直接使用。
 * 关键点：
 * - 使用与正文一致的字体与字号（16pt 仿宋 + 拉丁回退），减少测量偏差；
 * - `getBoundingClientRect()` 返回 px，这里统一换算成 pt（px * 0.75）；
 * - DOM 不可用时回退到 canvas 测量，避免运行期异常。
 */
const measureTextWidth = (
  text: string,
  fontFamily = 'Times New Roman, 方正仿宋_GBK, FangSong, STFangsong, Arial',
  fontSizePt = 16
) => {
  if (!text) return 0;
  const span = document.createElement('span');
  span.style.visibility = 'hidden';
  span.style.position = 'absolute';
  span.style.left = '-99999px';
  span.style.top = '-99999px';
  span.style.whiteSpace = 'nowrap';
  span.style.fontFamily = fontFamily;
  span.style.fontSize = `${fontSizePt}pt`;
  span.style.fontWeight = '400';
  span.style.letterSpacing = 'normal';
  span.textContent = text;

  document.body.appendChild(span);
  const widthPx = span.getBoundingClientRect().width;
  document.body.removeChild(span);
  return widthPx;
};

const renderAgencyAgainstDate = (agency: string, dateText: string, options = DEFAULTS) => {
  // 多机关并列时，以“最后一个机关”作为与成文日期的准居中对齐基准
  const agencySegments = agency
    .split(/[\u3000\s]{2,}/)
    .map((v) => v.trim())
    .filter(Boolean);
  const alignAgency =
    agencySegments.length > 0 ? agencySegments[agencySegments.length - 1] : agency.trim();
  const agencyWidth = measureTextWidth(
    alignAgency,
    `Times New Roman, ${BASE_FONT}, Arial`,
    options.text.fontSize
  );
  const dateWidth = measureTextWidth(
    dateText,
    `Times New Roman, ${BASE_FONT}, Arial`,
    options.text.fontSize
  );
  // 与日期行统一采用 margin-right，避免 padding 与 margin 混用导致视觉错位
  const datePaddingRightPt = Math.round(64 * (options.text.fontSize / 16));
  const rawAgencyMarginRight = Math.ceil(
    (dateWidth / 2 - agencyWidth / 2) / 1.34 + datePaddingRightPt + 16
  );
  const agencyMarginRight = Math.max(0, rawAgencyMarginRight);
  const STYLE_RIGHT_BODY = `margin: 0; font-size: ${options.text.fontSize}pt; line-height: ${options.text.lineHeight}; font-family: ${BASE_FONT}; text-align: right;`;
  return `<p style="${STYLE_RIGHT_BODY} margin-right: ${agencyMarginRight}pt;">${wrapLatinOnly(agency)}</p>`;
};

export const parse = (text: string, options = DEFAULTS) => {
  // ==================== 2. 深度合并配置 ====================
  function deepMerge(target: any, source: any) {
    const merged = { ...target };
    for (const key in source) {
      if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
        merged[key] = deepMerge(target[key] || {}, source[key]);
      } else {
        merged[key] = source[key];
      }
    }
    return merged;
  }

  const cfg = deepMerge(DEFAULTS, options);

  // ==================== 3. 根据配置生成内联样式 ====================
  function makeStyle(type: string) {
    const el = cfg[type];
    const parts = [];
    if (el.fontFamily) parts.push(`font-family:${el.fontFamily}`);
    if (el.fontSize != null) parts.push(`font-size:${el.fontSize}pt`);
    if (el.lineHeight != null) parts.push(`line-height:${el.lineHeight}`);
    if (el.textIndent != null) parts.push(`text-indent:${el.textIndent}`);
    if (el.textAlign) parts.push(`text-align:${el.textAlign}`);
    if (el.fontWeight) parts.push(`font-weight:${el.fontWeight}`);
    if (el.paddingRight) parts.push(`padding-right:${el.paddingRight}`);
    // 统一禁止 margin
    parts.push('margin:0');
    return parts.join(';');
  }

  // 空行样式：基于 text 元素，但缩进强制为 0
  function spacerStyle() {
    const textCfg = cfg.text;
    const parts = [
      `font-family:${textCfg.fontFamily || BASE_FONT}`,
      `font-size:${textCfg.fontSize || 16}pt`,
      `line-height:${textCfg.lineHeight || 2}`,
      'text-indent:0',
      'margin:0',
    ];
    return parts.join(';');
  }

  // ==================== 4. 输入预处理 ====================
  if (!text || text.trim() === '') return '';
  const blocks = text
    .trim()
    .split(/\n+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (blocks.length === 0) return '';

  // ==================== 5. 识别与归类 ====================
  const pool: { type: string; content: string }[] = []; // { type, content }

  // 标题
  pool.push({ type: 'title', content: blocks[0] });
  // 标题后空行
  pool.push({ type: 'spacer', content: '&nbsp;' });

  // 主送机关（标题后第一个以冒号结尾的块）
  let startIdx = 1;
  if (blocks.length > 1 && blocks[1].match(/[：:]$/)) {
    const cand = blocks[1];
    const heading1Re = /^[一二三四五六七八九十]+、/;
    const heading2Re = /^（[一二三四五六七八九十]+）/;
    if (!heading1Re.test(cand) && !heading2Re.test(cand)) {
      pool.push({ type: 'receiver', content: cand });
      startIdx = 2;
    }
  }

  // 从尾部识别：成文日期 → 署名 → 附件
  let lastIdx = blocks.length - 1;
  const tailItems = [];
  const dateRe = /^.{1,4}\s*年\s*.{1,3}\s*月\s*.{1,3}\s*日$/;
  const attachRe = /^附件[：:]/;
  const headingRe = [
    /^[一二三四五六七八九十]+、/,
    /^（[一二三四五六七八九十]+）/,
    /^\d+\./,
    /^（\d+）/,
  ];

  // 二级标题若与正文同行，仅保留首句为标题，其余回落正文。
  const splitHeadingSentence = (line: string): { heading: string; rest: string } => {
    const sentenceEnd = line.search(/[。！？；!?;]/);
    if (sentenceEnd < 0) {
      return { heading: line.trim(), rest: '' };
    }
    const cut = sentenceEnd + 1;
    return {
      heading: line.slice(0, cut).trim(),
      rest: line.slice(cut).trim(),
    };
  };

  // 成文日期
  if (lastIdx >= startIdx && dateRe.test(blocks[lastIdx])) {
    tailItems.unshift({ type: 'date', content: blocks[lastIdx] });
    lastIdx--;
  }

  // 署名
  if (lastIdx >= startIdx) {
    const cand = blocks[lastIdx];
    const isHeading = headingRe.some((re) => re.test(cand));
    const isAttach = attachRe.test(cand) || /^附件\d+/.test(cand);
    const isDate = dateRe.test(cand);
    const isReceiver = cand.match(/[：:]$/) && !isHeading;
    if (!isHeading && !isAttach && !isDate && !isReceiver) {
      tailItems.unshift({ type: 'sign', content: cand });
      lastIdx--;
    }
  }

  // 附件
  if (lastIdx >= startIdx && (attachRe.test(blocks[lastIdx]) || /^附件\d+/.test(blocks[lastIdx]))) {
    tailItems.unshift({ type: 'attachment', content: blocks[lastIdx] });
    lastIdx--;
  }

  // 中间部分
  for (let i = startIdx; i <= lastIdx; i++) {
    const block = blocks[i];
    if (headingRe[0].test(block)) {
      pool.push({ type: 'heading1', content: block });
    } else if (headingRe[1].test(block)) {
      const { heading, rest } = splitHeadingSentence(block);
      pool.push({ type: 'heading2', content: heading });
      if (rest) {
        pool.push({ type: 'text', content: rest });
      }
    } else if (headingRe[2].test(block)) {
      pool.push({ type: 'heading3', content: block });
    } else if (headingRe[3].test(block)) {
      pool.push({ type: 'heading4', content: block });
    } else if (attachRe.test(block) || /^附件\d+/.test(block)) {
      pool.push({ type: 'attachment', content: block });
    } else {
      pool.push({ type: 'text', content: block });
    }
  }

  // 尾部插入（含必要空行）
  if (tailItems.length > 0) {
    // 如果第一个尾部元素是附件，在其前插入空行
    if (tailItems[0].type === 'attachment') {
      tailItems.unshift({ type: 'spacer', content: '&nbsp;' });
    }
    // 如果存在署名，且其前面没有紧邻的空行，则插入空行
    for (let i = 0; i < tailItems.length; i++) {
      if (tailItems[i].type === 'sign') {
        if (i === 0 || tailItems[i - 1].type !== 'spacer') {
          tailItems.splice(i, 0, { type: 'spacer', content: '&nbsp;' });
          i++;
        }
      }
    }
    pool.push(...tailItems);
  }

  // ==================== 6. 生成 HTML ====================
  const htmlParts = pool.map((item, i) => {
    if (item.type === 'sign' && pool[i + 1] && pool[i + 1].type === 'date') {
      return renderAgencyAgainstDate(item.content, pool[i + 1].content);
    }
    const style = item.type === 'spacer' ? spacerStyle() : makeStyle(item.type);
    return `<p style="${style}">${item.content}</p>`;
  });

  // 容器：仅控制纸张效果，不设置字体（由内联覆盖）
  return htmlParts.join('');
};
