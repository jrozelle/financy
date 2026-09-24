// Types de static/modules/tabs/tools.js : actions partagees avec le menu.
export declare function triggerAutoSnapshot(): Promise<void>;
export declare function triggerPricesRefresh(onlyStale?: boolean): Promise<void>;
export declare function loadSchedulerStatus(): Promise<void>;
