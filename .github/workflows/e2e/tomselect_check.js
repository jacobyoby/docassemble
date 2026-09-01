// Browser e2e for the multiselect autocomplete (issue #280): the Tom
// Select widget must render, accept picks, and submit through the
// unchanged form encoding. Run with PUPPETEER_EXECUTABLE_PATH set.
const puppeteer = require("puppeteer-core");
(async () => {
  const browser = await puppeteer.launch({
    executablePath: process.env.PUPPETEER_EXECUTABLE_PATH,
    headless: "new",
  });
  const page = await browser.newPage();
  await page.goto("http://localhost:8080/interview?i=docassemble.demo:data/questions/test_autocomplete.yml", { waitUntil: "networkidle2", timeout: 60000 });
  await page.waitForSelector(".ts-wrapper", { timeout: 20000 });
  console.log("widget: ts-wrapper rendered");
  const picked = await page.evaluate(() => {
    const sel = document.querySelector("select.damultiselect");
    const ts = sel && sel.tomselect;
    if (!ts) return "no tomselect instance";
    const byLabel = {};
    for (const [val, opt] of Object.entries(ts.options)) {
      byLabel[(opt.text || "").trim()] = val;
    }
    ts.addItem(byLabel["apple"]);
    ts.addItem(byLabel["cherry"]);
    return Array.from(sel.selectedOptions).length + " selected";
  });
  console.log("selected via widget:", picked);
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle2", timeout: 30000 }),
    page.click("button[type=submit].btn-primary, button[name='X211bHRpcGxlX2Nob2ljZQ'], #da-continue-button, button.btn-da"),
  ]).catch(() => {});
  const body = await page.evaluate(() => document.body.innerText);
  console.log(/You chose apple and cherry/.test(body) ? "PASS: result renders" : "FAIL: result was: " + body.slice(0, 200));
  await browser.close();
})();
