// Where the page finds things. Both end with a slash.

// The API (deploy/sam): GET memes, POST meme. The ApiUrl output of the SAM stack.
export const API_BASE = "https://l7w2tpdtktvosvtyhmz2nkvxuq0wosod.lambda-url.ap-southeast-1.on.aws/";

// Template images. Relative = next to this page; to move them to a CDN, set an absolute
// URL here (the host must send CORS headers, or PNG export is blocked).
export const IMAGE_BASE = "images/";
