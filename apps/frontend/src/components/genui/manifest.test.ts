import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { COMPONENT_REGISTRY } from './registry';

// contracts/json-schema/ui-components.json is generated from ai/agent/ui.py. A component
// added on only one side fails here (and in tests/unit/test_ui_manifest.py for Python).
const manifest = JSON.parse(
  readFileSync(
    resolve(__dirname, '../../../../../contracts/json-schema/ui-components.json'),
    'utf8'
  )
) as { components: { name: string; selectable: boolean }[] };

describe('component registry', () => {
  it('has exactly the components the server manifest declares', () => {
    const server = manifest.components.map((c) => c.name).sort();
    expect(Object.keys(COMPONENT_REGISTRY).sort()).toEqual(server);
  });

  it('knows the server-controlled components', () => {
    const controlled = manifest.components.filter((c) => !c.selectable).map((c) => c.name);
    expect(controlled.sort()).toEqual(['approval_request', 'clarification']);
  });
});
