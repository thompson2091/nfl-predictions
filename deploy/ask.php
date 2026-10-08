<?php
/**
 * Ask about a game — a thin proxy in front of the Anthropic API.
 *
 * THE BROWSER NEVER SEES THE KEY AND NEVER SUPPLIES THE CONTEXT.
 *
 * The page is static files, so a question answered from live data has to go
 * through something server-side. That something is a liability if it is built
 * carelessly: an endpoint that forwards whatever it is given, keyed to a
 * payment method, is a free general-purpose model for anyone who finds the
 * URL. Two rules keep it from being one.
 *
 *   1. The CONTEXT comes from files on this server, chosen by a game id that
 *      is matched against the files that exist. Nothing the reader types
 *      becomes context, so the endpoint can only ever answer questions about
 *      this week's games.
 *   2. The RATE is capped per address and in total, in files under a
 *      directory only this script writes. The daily cap is the real
 *      protection — a per-IP limit alone is a limit per proxy.
 *
 * THE MODEL ASKS FOR THE DATA IT NEEDS, which is the whole change here.
 *
 * It used to get one fixed brief per game: the line, both models, the
 * distribution, and the eight best-priced and eight likeliest players per
 * market. A fixed guess, and measured against what the app actually draws it
 * was wrong in six places — every priced player is about forty a game and
 * sixteen traveled; the best price, the books quoting, the second per-$100
 * basis and the Pass/Leans/Strong verdict were on every board row and in no
 * brief; the game's angles were not there at all. Two of those cannot be
 * fixed by making the brief fatter: the whole angles table is 1.2 MB and the
 * whole season record is 254 KB, so "how has the model done on Dallas?" was
 * unanswerable from any per-game file however large.
 *
 * So a ~1.3 KB core travels with every question and the model calls
 * `get_data` for what it needs. The security property is unchanged and worth
 * stating exactly: the model supplies a slice NAME FROM A FIXED ENUM, this
 * script maps that name to a path built from the already-validated game id,
 * and an unrecognised name comes back as an error string rather than as a
 * file read. A reader can influence WHICH of our own published slices gets
 * fetched. A reader still cannot supply any of it, name a path, or reach a
 * file this script does not list.
 *
 * Written for PHP 5.5, which is what this host runs: no null coalescing, no
 * scalar type hints, no arrow functions.
 */

header('Content-Type: application/json; charset=utf-8');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store');

// ---------------------------------------------------------------- settings

$KEY_FILE   = '/etc/picksix/anthropic.key';   // outside the web root
$CTX_DIR    = __DIR__ . '/data/ask';          // one brief per game
$STATE_DIR  = '/var/lib/picksix';             // counters; not web readable
$MODEL      = 'claude-opus-5';
// Three markets, one paragraph each, plus the caveats that have to travel
// with them. At 900 the third market came back truncated mid-sentence.
$MAX_TOKENS = 1400;
$MAX_Q      = 400;        // characters; a question, not a document
$TIMEOUT    = 45;         // per upstream call

// THE CAPS, AND WHAT EACH ONE IS FOR.
//
// `$PER_DAY` is a WORST-CASE BILL, not an expected one, so it is costed
// rather than chosen. Measured on the real slices: the system block is ~1,500
// tokens and is cached, a slice is ~3,500 and never can be — it arrives as a
// tool_result in the messages — so a question that fetches once is about
// 4,000 effective input tokens and 900 out across two calls. At roughly Opus
// rates that is near $0.13 a question, which puts 750 a day at about $95 of
// exposure. 300 was set when one question was one call against a 10 KB brief.
//
// `$PER_IP_DAY` is the one that was MISSING, and it mattered more than the
// total. At 15 an hour one address could ask 360 times a day against a
// 300-a-day budget — so a single reader, or a single script, could spend the
// whole allowance and lock everyone else out until midnight while staying
// inside every limit this file declared. 50 holds one address to under a
// fifteenth of the day.
$PER_IP_HR  = 15;
$PER_IP_DAY = 50;
$PER_DAY    = 750;

// HOW MANY TIMES THE MODEL MAY GO BACK FOR MORE, and the two budgets that
// stop a question from pulling the whole site.
//
// The page gives up at 60 seconds and shows "that took too long", so the
// REAL limit is wall clock, not round trips: four calls at the 45-second
// per-call timeout is three minutes against a reader who left after one.
// $DEADLINE is checked before each call and is what actually binds.
$MAX_ROUNDS   = 4;
$SLICE_BYTES  = 90000;    // total slice data one question may pull
$DEADLINE     = 48;       // seconds from the first call; under the page's 60

// Every slice `get_data` can return, and the file each one resolves to.
// `{gid}` is the game id this script already validated by shape and matched
// against the files on disk; `{team}` is checked against the two teams named
// in THIS game's core before it is used. Nothing else is interpolated, and a
// name absent from this map is an error rather than a path.
$SLICE_FILES = array(
    'game'    => 'game/{gid}.json',
    'players' => 'players/{gid}.json',
    'angles'  => 'angles/{gid}.json',
    'record'  => 'record/season.json',
    'team'    => 'team/{team}.json',
);

function fail($code, $msg) {
    http_response_code($code);
    echo json_encode(array('error' => $msg));
    exit;
}

// ---------------------------------------------------------------- input

if ($_SERVER['REQUEST_METHOD'] !== 'POST') fail(405, 'POST only');
$raw = file_get_contents('php://input');
if (strlen($raw) > 4000) fail(413, 'too long');
$in = json_decode($raw, true);
if (!is_array($in)) fail(400, 'expected JSON');

$game = isset($in['game']) ? (string)$in['game'] : '';
$q    = isset($in['q'])    ? trim((string)$in['q']) : '';

// A game id is two team codes and an underscore. Validated by SHAPE before it
// is ever used to build a path, so a traversal cannot be attempted at all.
if (!preg_match('/^[A-Z]{2,4}_[A-Z]{2,4}$/', $game)) fail(400, 'unknown game');
if ($q === '') fail(400, 'ask something');
if (mb_strlen($q) > $MAX_Q) fail(400, 'question too long');

$ctx_file = $CTX_DIR . '/core/' . $game . '.json';
// A build that predates the slices still has the flat brief. Falling back to
// it means a deploy of the page and a deploy of this script do not have to
// land in the same minute — and the fallback is the OLD brief, which is
// thinner but correct, rather than an error page.
if (!is_readable($ctx_file)) $ctx_file = $CTX_DIR . '/' . $game . '.json';
if (!is_readable($ctx_file)) fail(404, 'no data for that game this week');

// ---------------------------------------------------------------- rate limit

function bump($dir, $name, $window, $limit) {
    if (!is_dir($dir)) @mkdir($dir, 0700, true);
    $path = $dir . '/' . $name;
    $now = time();
    $fh = @fopen($path, 'c+');
    if (!$fh) return true;              // cannot count: allow, do not break
    flock($fh, LOCK_EX);
    $body = stream_get_contents($fh);
    $rows = $body ? json_decode($body, true) : array();
    if (!is_array($rows)) $rows = array();
    $rows = array_values(array_filter($rows, function ($t) use ($now, $window) {
        return ($now - $t) < $window;
    }));
    $ok = count($rows) < $limit;
    if ($ok) $rows[] = $now;
    ftruncate($fh, 0);
    rewind($fh);
    fwrite($fh, json_encode($rows));
    flock($fh, LOCK_UN);
    fclose($fh);
    return $ok;
}

$ip = isset($_SERVER['REMOTE_ADDR']) ? $_SERVER['REMOTE_ADDR'] : 'unknown';
// THE PER-ADDRESS CAPS FIRST, so one reader spending their own allowance does
// not spend the day's. Ordered the other way round, every refusal a heavy
// user earns is still counted against the total that protects everyone else.
$me = 'ip-' . md5($ip);
if (!bump($STATE_DIR, $me . '-day.json', 86400, $PER_IP_DAY)) {
    fail(429, 'you have asked a lot today — try again tomorrow');
}
if (!bump($STATE_DIR, $me . '.json', 3600, $PER_IP_HR)) {
    fail(429, 'too many questions this hour — try again shortly');
}
if (!bump($STATE_DIR, 'all.json', 86400, $PER_DAY)) {
    fail(429, 'the daily question budget is used up — try tomorrow');
}

// ---------------------------------------------------------------- key

if (!is_readable($KEY_FILE)) fail(503, 'the question service is not configured');
$key = trim(file_get_contents($KEY_FILE));
if ($key === '') fail(503, 'the question service is not configured');

// ---------------------------------------------------------------- call

$ctx = file_get_contents($ctx_file);

// The two teams in this game, read from the CORE rather than from the game
// id, so `team` is checked against what the data says is playing.
$core_json = json_decode($ctx, true);
$teams = array();
if (is_array($core_json)) {
    foreach (array('away', 'home') as $k) {
        if (isset($core_json[$k]) && is_string($core_json[$k])) {
            $teams[] = $core_json[$k];
        }
    }
}
if (!$teams) {
    // The flat-brief fallback has no away/home, so fall back to the id —
    // which this script validated by shape before anything used it.
    $teams = explode('_', $game);
}

/**
 * One `get_data` call, resolved to a slice of this game's data or to a
 * sentence explaining why not.
 *
 * NO READER STRING REACHES A PATH. `$name` is looked up in `$files`, which
 * is a literal in this file; `$gid` was matched against `^[A-Z]{2,4}_[A-Z]{2,4}$`
 * and against the files on disk; `$team` is checked by identity against the
 * two teams this game's own core names. An unrecognised slice returns a
 * string, so the model is told what it can have instead of the request
 * failing silently.
 */
function slice_body($name, $team, $gid, $teams, $dir, $files) {
    if (!is_string($name) || !isset($files[$name])) {
        return 'There is no slice called "' . (is_string($name) ? $name : '?')
             . '". You can ask for: ' . implode(', ', array_keys($files)) . '.';
    }
    $path = $files[$name];
    if (strpos($path, '{team}') !== false) {
        $team = is_string($team) ? strtoupper(trim($team)) : '';
        if (!in_array($team, $teams, true)) {
            return 'The team slice needs team set to '
                 . implode(' or ', $teams) . ' — the two teams in this game.';
        }
        $path = str_replace('{team}', $team, $path);
    }
    $path = str_replace('{gid}', $gid, $path);
    $full = $dir . '/' . $path;
    if (!is_readable($full)) {
        return 'That slice has not been built for this week, so the data '
             . 'does not exist rather than being withheld.';
    }
    return file_get_contents($full);
}

function api_call($key, $body, $timeout) {
    $ch = curl_init('https://api.anthropic.com/v1/messages');
    curl_setopt_array($ch, array(
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_POST => true,
        CURLOPT_TIMEOUT => $timeout,
        CURLOPT_POSTFIELDS => json_encode($body),
        CURLOPT_HTTPHEADER => array(
            'Content-Type: application/json',
            'x-api-key: ' . $key,
            'anthropic-version: 2023-06-01',
        ),
    ));
    $resp = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $err  = curl_error($ch);
    curl_close($ch);
    return array($code, $resp, $err);
}

$system = "You answer questions about one NFL game for a betting site read by "
  . "people who do not bet much.\n\n"
  // THE TOOL IS THE FIRST INSTRUCTION, because the core below is deliberately
  // thin and a model that answers from it alone will say "the data does not
  // include that" about numbers printed on the screen the reader is looking
  // at. That was the old failure and it looked like honesty.
  . "FETCH WHAT YOU NEED BEFORE YOU ANSWER. The block below is a summary. "
  . "Call get_data for anything it does not already contain — a player's "
  . "price or projection, the best price available, the matchup, the public "
  . "split, this game's angles, how our model has done. `you_can_fetch` in "
  . "the data lists every slice and what is in it. Ask for several in one "
  . "turn when a question touches several. Do not guess at a number you "
  . "could have fetched, and do not tell the reader data is unavailable "
  . "until you have asked for it.\n\n"
  . "ANSWER ONLY FROM THE DATA, except that you may use web search for "
  . "news the data cannot contain — an injury reported today, a weather "
  . "forecast, a coaching change. Everything numeric must come from the data.\n\n"
  . "If the data does not answer the question, say so plainly and say what "
  . "would answer it. Never invent a number, a price or a player.\n\n"
  // ANSWER THE QUESTION. The rule used to read "no betting advice", and on
  // "read me the spread, the moneyline and the total" the model spent its
  // first paragraph announcing what it would not do and then answered
  // anyway. Describing what the site's own numbers say is the product, not
  // advice: every figure it is being asked about is already printed on the
  // card above the box.
  . "WHAT THE NUMBERS SAY IS THE ANSWER. Asked to read the spread, the "
  . "moneyline or the total, give each one: what the market's number "
  . "implies, what our model makes it, where the two disagree and what in "
  . "the data explains the gap. Say which side our model leans and by how "
  . "much — that is a description of the model, not a recommendation.\n\n"
  . "Never open with a disclaimer or a statement of what you will not do. "
  . "Answer first. Do not refuse a question the data can answer.\n\n"
  . "What you do NOT do: tell the reader what to bet, how much to stake, or "
  . "that anything is a lock, a guarantee, free money or a sure thing. No "
  . "confidence you cannot source. Where a number rests on a small sample "
  . "or a wide interval, say so in the same breath as the number.\n\n"
  // THE THREE NUMBERS, NAMED THE WAY THE PAGE NAMES THEM. A reader who has
  // just read "Model 64%, Book 44%, Adjusted 46%" off the screen is owed the
  // same three words back, and the gap between a positive edge and a losing
  // bet is the single thing on this site most often misread.
  . "THE VOCABULARY, which matches the screen: Model is our number built "
  . "with no sight of the price. Book is the price with the bookmaker's cut "
  . "removed. Adjusted is the two blended, and is the number we stand "
  . "behind. Edge is Adjusted minus Book in points of chance — and because "
  . "both already have the cut removed, a small positive edge can still "
  . "lose money. Per $100 is what clears the cut, and it is the number that "
  . "says whether a bet pays. Where the two disagree, say so.\n\n"
  . "Four short paragraphs at most, one per market when several are asked "
  . "about. Plain English; spell out any jargon you use — say what a "
  . "moneyline is the first time you use the word.\n\n"
  . "Use AMERICAN spelling: favorite, defense, offense, color. This is "
  . "American football read by Americans.\n\n"
  . "A negative spread means the HOME team is favored.\n\n"
  // PLAYERS CHANGE TEAMS, AND THE MODEL'S MEMORY IS OLDER THAN THE DATA.
  // Asked which team a player is on, a model with no team in front of it
  // answers from training and sounds certain doing it. The rosters below are
  // ingested weekly and are the authority, so say which one wins.
  . "The teams, prices and projections in the data are THIS WEEK'S, "
  . "ingested for this game. Players change teams between seasons. If the "
  . "data disagrees with what you remember about a player's team, the data "
  . "is right and your memory is out of date — use the data and do not "
  . "correct it.\n\n"
  . "THE GAME:\n" . $ctx;

$get_data = array(
    'name' => 'get_data',
    'description' => 'Fetch a slice of this site\'s own data for this game. '
        . 'Call it before answering anything the summary does not already '
        . 'contain. See `you_can_fetch` in the summary for what each slice '
        . 'holds.',
    'input_schema' => array(
        'type' => 'object',
        'properties' => array(
            'slice' => array(
                'type' => 'string',
                'enum' => array_keys($SLICE_FILES),
                'description' => 'which slice to fetch',
            ),
            'team' => array(
                'type' => 'string',
                'description' => 'three-letter team code; required when '
                    . 'slice is "team", ignored otherwise',
            ),
        ),
        'required' => array('slice'),
    ),
);
$web_search = array(
    'type' => 'web_search_20250305',
    'name' => 'web_search',
    'max_uses' => 3,
);

// ---------------------------------------------------------------- the loop
//
// The model answers, or asks for a slice and then answers. `get_data` is
// taken AWAY on the last allowed round rather than the loop simply stopping:
// a model mid-way through gathering, handed no tools and no instruction to
// stop, would otherwise have the budget run out underneath it and return
// nothing at all. Without the tool it has to answer from what it has, and
// says what it is missing.

$started   = time();
$messages  = array(array('role' => 'user', 'content' => $q));
$slice_got = 0;
$searched  = false;
$fetched   = array();
$text      = '';

for ($round = 0; $round <= $MAX_ROUNDS; $round++) {
    $last = ($round === $MAX_ROUNDS)
            || ((time() - $started) > $DEADLINE)
            || ($slice_got >= $SLICE_BYTES);
    $tools = $last ? array($web_search) : array($get_data, $web_search);
    $body = array(
        'model' => $MODEL,
        'max_tokens' => $MAX_TOKENS,
        // CACHED, because the loop resends it. The instructions and the core
        // are the same bytes on every round; without this a question that
        // fetches twice pays for them three times.
        'system' => array(array(
            'type' => 'text',
            'text' => $system,
            'cache_control' => array('type' => 'ephemeral'),
        )),
        'tools' => $tools,
        'messages' => $messages,
    );
    list($code, $resp, $err) = api_call($key, $body, $TIMEOUT);
    if ($resp === false) fail(502, 'could not reach the model (' . $err . ')');
    if ($code !== 200) {
        // The upstream body is NOT returned: it can echo request details,
        // and this endpoint is public. The status is enough to act on.
        fail(502, 'the model returned ' . $code);
    }
    $out = json_decode($resp, true);
    if (!is_array($out) || !isset($out['content']) || !is_array($out['content'])) {
        fail(502, 'the model returned nothing');
    }

    // THIS ROUND'S TEXT, NOT EVERY ROUND'S. A turn that ends in a tool call
    // may carry a line of preamble — "let me look at the players" — and
    // concatenating those across rounds reads as the model narrating its own
    // plumbing to a reader who asked about a spread.
    $text = '';
    $wants = array();
    foreach ($out['content'] as $block) {
        $type = isset($block['type']) ? $block['type'] : '';
        if ($type === 'text' && isset($block['text'])) {
            $text .= $block['text'];
        } elseif ($type === 'tool_use') {
            $wants[] = $block;
        } elseif (strpos($type, 'server_tool') === 0
                  || strpos($type, 'web_search') === 0) {
            $searched = true;
        }
    }

    $stop = isset($out['stop_reason']) ? $out['stop_reason'] : '';
    if ($stop !== 'tool_use' || !$wants) break;

    // The assistant's turn goes back VERBATIM. Anthropic's API requires the
    // tool_use blocks it sent to be echoed with their ids, and a
    // reconstructed copy is a different message.
    $messages[] = array('role' => 'assistant', 'content' => $out['content']);

    $results = array();
    foreach ($wants as $block) {
        $name  = isset($block['name']) ? $block['name'] : '';
        $input = isset($block['input']) && is_array($block['input'])
                 ? $block['input'] : array();
        if ($name !== 'get_data') {
            $out_text = 'There is no tool called "' . $name . '".';
        } elseif ($slice_got >= $SLICE_BYTES) {
            $out_text = 'The data budget for this question is spent. Answer '
                      . 'from what you already have and say what is missing.';
        } else {
            $out_text = slice_body(
                isset($input['slice']) ? $input['slice'] : null,
                isset($input['team']) ? $input['team'] : null,
                $game, $teams, $CTX_DIR, $SLICE_FILES);
            $slice_got += strlen($out_text);
            if (isset($input['slice']) && is_string($input['slice'])) {
                $fetched[$input['slice']] = true;
            }
        }
        $results[] = array(
            'type' => 'tool_result',
            'tool_use_id' => isset($block['id']) ? $block['id'] : '',
            'content' => $out_text,
        );
    }
    $messages[] = array('role' => 'user', 'content' => $results);
}

if (trim($text) === '') fail(502, 'the model returned nothing');

// WHAT IT LOOKED AT, back to the page. An answer that reads thin is
// either a thin question or a slice that was never fetched, and from the
// outside those are indistinguishable without this.
echo json_encode(array('answer' => trim($text), 'searched' => $searched,
                       'used' => array_keys($fetched)));
