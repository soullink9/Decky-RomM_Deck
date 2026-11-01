// Just enough typing for JSX; the React and Decky objects come from Decky Loader at runtime.
declare namespace JSX {
  interface IntrinsicElements { [tag: string]: any }
  type Element = any;
}
