export declare const COLORS: Set<string>;
export declare const HEX: Map<string, string>;
export declare function isUnitless(prop: string): boolean;
export declare function cssValue(prop: string, value: string | number): string;
export declare function kebab(prop: string): string;
export declare function colorName(value: string): string | null;
export declare function toClasses(prop: string, value: string | number, opts?: { strict?: boolean }): string[];
