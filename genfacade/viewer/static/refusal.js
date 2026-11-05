// Отказ сервера — `detail` вида {code, text, detail} (genfacade/viewer/app.py, refuse): страница
// показывает текст из ответа и своих списков кодов не держит (docs/clean-contour.md, п. 17).

export class Refused extends Error {
  constructor(refusal) {
    super(refusalText(refusal));
    this.refusal = refusal;
  }
}

// detail — строка или строки по полям (ошибки схемы запроса).
export function refusalText({ text, detail }) {
  const lines = [detail].flat().filter(Boolean);
  return lines.length ? `${text}: ${lines.join("\n")}` : text;
}

// Ответ без отказа из контракта (обрыв, прокси) кода не получает: показываем, что пришло.
export async function refusedFrom(res) {
  const data = await res.json().catch(() => null);
  if (data?.detail?.code) return new Refused(data.detail);
  return new Error(`сервер ответил ${res.status} ${res.statusText} без причины`);
}
