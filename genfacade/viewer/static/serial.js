// Задачи с одним ключом — по одной, в порядке вызова: запрос на позднее действие не обгонит
// запрос на раннее, итог не зависит от того, чей ответ пришёл первым (docs/clean-contour.md, п. 14).
export function serial() {
  const tails = new Map();
  return (key, task) => {
    const run = (tails.get(key) ?? Promise.resolve()).then(task);
    tails.set(key, run.catch(() => {})); // отказ одной задачи не останавливает следующие
    return run;
  };
}
