export interface ContentIndex {
  modules: { id: string; name: string; items_count: number; published?: boolean }[];
  partial: boolean;
}
