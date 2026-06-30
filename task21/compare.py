"""
Task 21 — Сравнение стратегий чанкинга.

Запускает одни и те же запросы против обоих индексов и показывает разницу.
"""

import warnings
warnings.filterwarnings("ignore")

from search import cosine_search, load_index

QUERIES = [
    "как перевести деньги в Китай",
    "нотификация ФСБ для экспорта",
    "временный ввоз таможенная процедура",
]


def print_separator(char="─", width=70):
    print(char * width)


def compare_query(query: str):
    print_separator("═")
    print(f'  ЗАПРОС: "{query}"')
    print_separator("═")

    fixed_results = cosine_search(query, "fixed", top_k=3)
    struct_results = cosine_search(query, "struct", top_k=3)

    print(f"\n{'STRATEGY 1: Fixed (500 chars + overlap 100)':^70}")
    print_separator()
    for i, r in enumerate(fixed_results, 1):
        print(f"{i}. [{r['score']}] {r['title'][:45]} | {r['section'][:20]}")
        print(f"   Размер чанка: {r['char_count']} chars")
        print(f"   Превью: {r['text_preview'][:120]}...")
        print()

    print(f"\n{'STRATEGY 2: Struct (по заголовкам ##)':^70}")
    print_separator()
    for i, r in enumerate(struct_results, 1):
        print(f"{i}. [{r['score']}] {r['title'][:45]} | {r['section'][:20]}")
        print(f"   Размер чанка: {r['char_count']} chars")
        print(f"   Превью: {r['text_preview'][:120]}...")
        print()

    # Вывод победителя по топ-1 score
    best_fixed = fixed_results[0]["score"] if fixed_results else 0
    best_struct = struct_results[0]["score"] if struct_results else 0
    winner = "STRUCT ✅" if best_struct >= best_fixed else "FIXED ✅"
    diff = abs(best_struct - best_fixed)
    print(f"  Топ-1 score: Fixed={best_fixed}  Struct={best_struct}  → Победитель: {winner} (Δ={diff:.4f})")


def print_stats():
    print_separator("═")
    print("  СТАТИСТИКА ИНДЕКСОВ")
    print_separator("═")
    fixed_idx = load_index("fixed")
    struct_idx = load_index("struct")

    fixed_sizes = [c["char_count"] for c in fixed_idx]
    struct_sizes = [c["char_count"] for c in struct_idx]

    print(f"\n  Strategy 1 (Fixed):")
    print(f"    Чанков всего:  {len(fixed_idx)}")
    print(f"    Avg размер:    {sum(fixed_sizes)//len(fixed_sizes)} chars")
    print(f"    Min/Max:       {min(fixed_sizes)} / {max(fixed_sizes)} chars")

    print(f"\n  Strategy 2 (Struct):")
    print(f"    Чанков всего:  {len(struct_idx)}")
    print(f"    Avg размер:    {sum(struct_sizes)//len(struct_sizes)} chars")
    print(f"    Min/Max:       {min(struct_sizes)} / {max(struct_sizes)} chars")

    print(f"\n  Источников (документов): {len(set(c['source'] for c in fixed_idx))}")
    print()


def main():
    print("\n" + "=" * 70)
    print("  TASK 21: СРАВНЕНИЕ СТРАТЕГИЙ ЧАНКИНГА")
    print("  GigaEmbeddings + Cosine Similarity")
    print("=" * 70 + "\n")

    print("Загружаю модель и индексы...")
    print_stats()

    for query in QUERIES:
        compare_query(query)
        print()

    print_separator("═")
    print("  ВЫВОД:")
    print("  • Fixed-size: предсказуемый размер, но разрывает смысловые блоки")
    print("  • Struct:     целостные разделы, лучше качество поиска по теме")
    print("  • Рекомендация: Struct для структурированных MD/PDF документов")
    print_separator("═")


if __name__ == "__main__":
    main()
