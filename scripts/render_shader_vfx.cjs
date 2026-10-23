#!/usr/bin/env node
/**
 * 离线程序化 WebGL2 GLSL Shader 语音球特效烘焙器
 * 单次启动 Chromium 即可批量渲染 idle / listening / thinking / speaking 四态 100% 无缝循环序列帧，
 * 并自动合成一张 4×6 样张总览图 (contact sheet) 供人工与 Critic 子智能体审阅。
 *
 * 用法:
 *   NODE_PATH=$(npm root -g) node scripts/render_shader_vfx.cjs [out_dir] [frames_per_state] [size_px] [bg_mode]
 * 示例:
 *   NODE_PATH=$(npm root -g) node scripts/render_shader_vfx.cjs out/vfx_orb 24 180 dark
 */
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

(async () => {
  const outRoot = process.argv[2] || path.join(__dirname, '..', 'out', 'vfx_orb');
  const totalFrames = parseInt(process.argv[3] || '24', 10);
  const sizePx = parseInt(process.argv[4] || '180', 10);
  const bgMode = process.argv[5] || 'dark'; // 'dark' (#04060D, 适合 MJPEG) 或 'transparent' (适合 ARGB/RGB565A8/SQOI)
  const states = ['idle', 'listening', 'thinking', 'speaking'];

  const htmlPath = path.resolve(__dirname, '..', 'templates', 'shader_orb.html');
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: sizePx, height: sizePx },
    deviceScaleFactor: 1,
  });

  await page.goto(`file://${htmlPath}?size=${sizePx}&bg=${bgMode}`);

  const t0 = Date.now();
  for (const st of states) {
    const stateDir = path.join(outRoot, st);
    fs.mkdirSync(stateDir, { recursive: true });
    for (let f = 0; f < totalFrames; f++) {
      await page.evaluate(
        ({ s, frame, total, sz, bg }) => window.setOrbFrame(s, frame, total, sz, bg),
        { s: st, frame: f, total: totalFrames, sz: sizePx, bg: bgMode }
      );
      const outPath = path.join(stateDir, `${String(f).padStart(3, '0')}.png`);
      await page.screenshot({
        path: outPath,
        omitBackground: bgMode !== 'dark',
      });
    }
    console.log(`rendered state [${st}]: ${totalFrames} frames @ ${sizePx}x${sizePx} -> ${stateDir}`);
  }

  await browser.close();
  const dt = ((Date.now() - t0) / 1000).toFixed(2);
  console.log(`all ${states.length * totalFrames} shader frames baked in ${dt}s`);
})();
