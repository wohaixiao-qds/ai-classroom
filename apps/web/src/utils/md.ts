/** LLM 输出的 markdown 规整:修「孤儿/嵌套 **」导致的字面星号(答疑/批改共用)。
 *
 * GLM 病灶:①嵌套加粗「**A **B** C**」CommonMark 解析不了→整句字面;
 * ②落单 ** 奇数个→尾部字面。
 * 策略:①拍扁——嵌套特征(前段尾随空格 + 内段两端无空格)时 `**A **B** C**`→`**A B** C`,
 *   特征不满足的相邻合法加粗不动;②孤儿转义为字面星号(宁可不加粗,不露星号)。
 * 代码块/行内代码全程豁免(其内 ** 是内容)。 */

const CODE = String.fromCharCode(1); // 代码占位符(控制字符,正文不会出现)
const BOLD = String.fromCharCode(2); // 孤儿检测占位符

export function normalizeBold(md: string): string {
  const store: string[] = [];
  // 0) 代码块/行内代码豁免
  let t = md.replace(/```[\s\S]*?```|`[^`\n]+`/g, (m) => {
    store.push(m);
    return `${CODE}${store.length - 1}${CODE}`;
  });
  // 0.5) GLM 招牌句式「**标签:**内容」:冒号留在粗体内破坏右 flanking,
  //      CommonMark 判废整对→字面星号(实测 react-markdown 渲染复现)。冒号挪出粗体即可解析。
  t = t.replace(/\*\*([^*\n]*?):(\s*)\*\*/g, (_m, inner: string, sp: string) => `**${inner}**:${sp}`);
  // 1) 嵌套拍扁(最多三层迭代):**A␣**B** C** → **A␣B** C
  //    特征:X 尾随空白(嵌套误写的痕迹)、Y 两端无空白(真·紧贴的内层粗体)
  const nested =
    /\*\*([^*\n]*?\s)\*\*(\S(?:[^*\n]*\S)?)\*\*([^*\n]+?)\*\*/g;
  for (let i = 0; i < 3; i++) {
    const next = t.replace(nested, (_m, x: string, y: string, z: string) => `**${x}${y}** ${z}`);
    if (next === t) break;
    t = next;
  }
  // 1.5) 幂运算写法 2**3:字面转义,不参与配对(实测会干扰粗体配对)
  t = t.replace(/(\d)\*\*(\d)/g, "$1\\*\\*$2");
  // 2) 孤儿转义:**先全换占位符,能配对的还原,落单的转义成字面星号
  t = t.replace(/\*\*/g, BOLD);
  const pairRe = new RegExp(`${BOLD}([^${BOLD}\n]+?)${BOLD}`, "g");
  t = t.replace(pairRe, (_m, inner: string) => `**${inner}**`);
  t = t.split(BOLD).join("\\*\\*");
  // 3) 还原代码
  const codeRe = new RegExp(`${CODE}(\\d+)${CODE}`, "g");
  t = t.replace(codeRe, (_m, i: string) => store[Number(i)]);
  return t;
}
