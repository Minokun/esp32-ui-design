// SVG(单色图标) → 透明底 PNG，指定尺寸与颜色
// 用法: NODE_PATH=$(npm root -g) node svg2png.cjs in.svg out.png [64] [#EAF2FF]
const fs = require('fs');
const { chromium } = require('playwright');
(async () => {
  const [svgPath, out, sizeArg, color] = process.argv.slice(2);
  if (!svgPath || !out) { console.error('usage: svg2png.cjs in.svg out.png [size] [color]'); process.exit(2); }
  const size = parseInt(sizeArg || '64', 10);
  const fill = color || '#EAF2FF';
  let svg = fs.readFileSync(svgPath, 'utf8');
  svg = svg.replace(/<svg([^>]*)>/, (m, attrs) => {
    let a = attrs.replace(/\s(width|height)="[^"]*"/g, '');
    return `<svg${a} width="${size}" height="${size}" xmlns="http://www.w3.org/2000/svg">`;
  });
  const html = `<html><body style="margin:0;background:transparent">
    <div style="width:${size}px;height:${size}px;color:${fill}">${svg}</div>
  </body></html>`;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
  await page.setContent(html);
  await page.waitForTimeout(300);
  await page.screenshot({ path: out, omitBackground: true });
  await browser.close();
  console.log(`svg2png: ${out} ${size}x${size}`);
})();
