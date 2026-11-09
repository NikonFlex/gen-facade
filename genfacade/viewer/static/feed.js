// Подгрузка списка порциями без DOM (gf#356): какая порция следующая, когда конец, второй запрос
// не шлём, ошибка — отдельное состояние, из которого выходят повтором. Страница даёт `fetchPage(n)`
// → {items, pages} и `feed.onChange` (зовётся при каждой смене состояния); когда звать `more()` (часовой на экране), решает она.

export const Phase = Object.freeze({ IDLE: "idle", LOADING: "loading", ERROR: "error", DONE: "done" });

export function createFeed(fetchPage) {
  let generation = 0;
  const feed = {
    phase: Phase.IDLE, next: 1, items: [], error: null, onChange() {},
    // Следующая порция; false — запрос не ушёл (уже идёт или список кончился).
    async more() {
      if (feed.phase === Phase.LOADING || feed.phase === Phase.DONE) return false;
      const mine = generation, page = feed.next;
      feed.phase = Phase.LOADING; feed.error = null;
      feed.onChange(feed);
      try {
        const got = await fetchPage(page);
        if (mine !== generation) return false; // список начат заново, пока шёл запрос
        feed.items = feed.items.concat(got.items);
        feed.next = page + 1;
        feed.phase = page >= got.pages ? Phase.DONE : Phase.IDLE;
      } catch (e) {
        if (mine !== generation) return false;
        feed.phase = Phase.ERROR; feed.error = e;
      }
      feed.onChange(feed);
      return true;
    },
    // Новый фильтр или поиск: с начала, ответ старого запроса отбрасывается.
    reset() {
      generation += 1;
      Object.assign(feed, { phase: Phase.IDLE, next: 1, items: [], error: null });
    },
  };
  return feed;
}
