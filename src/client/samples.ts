import type { SampleListPayload } from './bridge';

export class SampleListView {
  constructor(private readonly element: HTMLElement) {}

  render(catalog: SampleListPayload): void {
    this.element.replaceChildren();
    if (!catalog.configured) {
      this.element.textContent = 'No sample registry.';
      return;
    }
    if (catalog.samples.length === 0) {
      this.element.textContent = 'No declared samples.';
      return;
    }

    for (const sample of catalog.samples) {
      const item = document.createElement('div');
      item.className = 'sample-item';

      const header = document.createElement('div');
      header.className = 'sample-header';
      const name = document.createElement('code');
      name.textContent = sample.name;
      header.append(name);

      if (sample.tags.length > 0) {
        const tags = document.createElement('div');
        tags.className = 'sample-tags';
        for (const tag of sample.tags) {
          const tagElement = document.createElement('span');
          tagElement.className = 'sample-tag';
          tagElement.textContent = tag;
          tags.append(tagElement);
        }
        header.append(tags);
      }

      item.append(header);
      if (sample.description) {
        const description = document.createElement('p');
        description.textContent = sample.description;
        item.append(description);
      }
      this.element.append(item);
    }
  }

  renderUnavailable(): void {
    this.element.replaceChildren();
    this.element.textContent = 'Sample registry unavailable.';
  }
}
