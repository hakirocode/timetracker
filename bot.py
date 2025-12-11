import asyncio
import logging
import os
from datetime import datetime, date, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ParseMode
from aiogram.utils import executor

from database import Database
from keyboards import *
from utils import generate_daily_report
import config

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Инициализация базы данных
db = Database(
    host=config.MYSQL_HOST,
    user=config.MYSQL_USER,
    password=config.MYSQL_PASSWORD,
    database=config.MYSQL_DATABASE
)

# Состояния FSM
class TimeTracking(StatesGroup):
    waiting_for_activity = State()
    waiting_for_duration = State()
    waiting_for_report_date = State()

# Команда /start
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    # Создаем пользователя
    db.create_user(user_id, username)
    
    await message.answer(
        f"🕒 Привет, {username}!\n\n"
        "Я бот для учета времени.\n\n"
        "<b>Что я умею:</b>\n"
        "• 📊 Добавлять активности\n"
        "• 📈 Создавать отчеты с диаграммами\n"
        "• 📅 Показывать статистику\n\n"
        "<b>Категории:</b>\n"
        "💼 Работа | 😴 Сон | 🎯 Отдых\n"
        "📚 Учеба | 🎮 Развлечения\n\n"
        "<i>Используйте кнопки ниже 👇</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard()
    )

# Команда /add - добавление активности
@dp.message_handler(commands=['add'])
async def cmd_add(message: types.Message):
    await message.answer(
        "📊 <b>Выберите тип активности:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_activities_keyboard()
    )
    await TimeTracking.waiting_for_activity.set()

# Обработчик выбора активности
@dp.message_handler(state=TimeTracking.waiting_for_activity)
async def process_activity(message: types.Message, state: FSMContext):
    activity_text = message.text
    activity_map = {
        "💼 Работа": "work",
        "😴 Сон": "sleep",
        "🎯 Отдых": "rest",
        "📚 Учеба": "study",
        "🎮 Развлечения": "entertainment"
    }
    
    if activity_text not in activity_map:
        await message.answer("Пожалуйста, выберите активность из кнопок:")
        return
    
    activity_type = activity_map[activity_text]
    await state.update_data(activity_type=activity_type)
    
    await message.answer(
        "⏱️ <b>Введите продолжительность в минутах:</b>\n\n"
        "<i>Примеры:</i>\n"
        "• <code>60</code> - 1 час\n"
        "• <code>90</code> - 1.5 часа\n"
        "• <code>120</code> - 2 часа\n\n"
        "<i>Или выберите быстрый вариант:</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_quick_time_keyboard()
    )
    await TimeTracking.waiting_for_duration.set()

# Обработчик быстрых кнопок времени
@dp.callback_query_handler(lambda c: c.data.startswith('quick_'), 
                          state=TimeTracking.waiting_for_duration)
async def process_quick_time(callback_query: types.CallbackQuery, state: FSMContext):
    minutes_map = {
        'quick_15': 15,
        'quick_30': 30,
        'quick_45': 45,
        'quick_60': 60,
        'quick_90': 90,
        'quick_120': 120
    }
    
    minutes = minutes_map.get(callback_query.data, 60)
    data = await state.get_data()
    activity_type = data['activity_type']
    
    user_id = callback_query.from_user.id
    entry_id = db.add_time_entry(user_id, activity_type, minutes)
    
    if entry_id:
        activity_names = {
            "work": "💼 Работа",
            "sleep": "😴 Сон",
            "rest": "🎯 Отдых",
            "study": "📚 Учеба",
            "entertainment": "🎮 Развлечения"
        }
        
        activity_name = activity_names.get(activity_type, activity_type)
        hours = minutes // 60
        mins = minutes % 60
        
        await bot.send_message(
            user_id,
            f"✅ <b>Добавлено!</b>\n\n"
            f"<b>Активность:</b> {activity_name}\n"
            f"<b>Время:</b> {hours}ч {mins}м\n"
            f"<b>Когда:</b> {datetime.now().strftime('%H:%M')}",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )
    else:
        await bot.send_message(
            user_id,
            "❌ <b>Ошибка!</b> Попробуйте еще раз.",
            parse_mode=ParseMode.HTML
        )
    
    await state.finish()
    await bot.answer_callback_query(callback_query.id)

# Обработчик ввода времени
@dp.message_handler(state=TimeTracking.waiting_for_duration)
async def process_duration(message: types.Message, state: FSMContext):
    try:
        duration_text = message.text.strip()
        
        # Обработка разных форматов
        if ':' in duration_text:
            # Формат ЧЧ:ММ
            try:
                parts = duration_text.split(':')
                if len(parts) == 2:
                    hours = int(parts[0]) if parts[0] else 0
                    minutes = int(parts[1]) if parts[1] else 0
                    duration_minutes = hours * 60 + minutes
                else:
                    duration_minutes = int(duration_text)
            except:
                duration_minutes = int(duration_text)
        elif '.' in duration_text or ',' in duration_text:
            # Формат с десятичной дробью
            duration_text = duration_text.replace(',', '.')
            try:
                hours = float(duration_text)
                duration_minutes = int(hours * 60)
            except:
                duration_minutes = int(duration_text)
        else:
            # Просто минуты
            duration_minutes = int(duration_text)
        
        if duration_minutes <= 0 or duration_minutes > 1440:
            await message.answer("❌ Некорректное время! Введите от 1 до 1440 минут:")
            return
        
        data = await state.get_data()
        activity_type = data['activity_type']
        
        user_id = message.from_user.id
        entry_id = db.add_time_entry(user_id, activity_type, duration_minutes)
        
        if entry_id:
            activity_names = {
                "work": "💼 Работа",
                "sleep": "😴 Сон",
                "rest": "🎯 Отдых",
                "study": "📚 Учеба",
                "entertainment": "🎮 Развлечения"
            }
            
            activity_name = activity_names.get(activity_type, activity_type)
            hours = duration_minutes // 60
            mins = duration_minutes % 60
            
            await message.answer(
                f"✅ <b>Добавлено!</b>\n\n"
                f"<b>Активность:</b> {activity_name}\n"
                f"<b>Время:</b> {hours}ч {mins}м",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_keyboard()
            )
        else:
            await message.answer("❌ Ошибка! Попробуйте еще раз.")
        
        await state.finish()
        
    except ValueError:
        await message.answer(
            "❌ Неверный формат!\n"
            "Введите число минут или время в формате:\n"
            "• 60 (минут)\n"
            "• 1.5 (часа)\n"
            "• 1:30 (часы:минуты)"
        )

# Команда /today - сегодняшние активности
@dp.message_handler(commands=['today'])
async def cmd_today(message: types.Message):
    user_id = message.from_user.id
    today = date.today()
    
    entries = db.get_user_entries_by_date(user_id, today)
    
    if not entries:
        await message.answer(
            "📭 <b>Сегодня еще нет записей</b>\n\n"
            "Добавьте первую активность!",
            parse_mode=ParseMode.HTML
        )
        return
    
    message_text = "📊 <b>Сегодняшние активности:</b>\n\n"
    total_minutes = 0
    
    activity_names = {
        "work": "💼 Работа",
        "sleep": "😴 Сон",
        "rest": "🎯 Отдых",
        "study": "📚 Учеба",
        "entertainment": "🎮 Развлечения"
    }
    
    for entry in entries:
        activity_type = entry['activity_type']
        duration = entry['duration_minutes']
        created_at = entry['created_at']
        
        hours = duration // 60
        minutes = duration % 60
        
        activity_name = activity_names.get(activity_type, activity_type)
        time_str = f"{hours}ч {minutes}м" if hours > 0 else f"{minutes}м"
        
        # Время создания
        try:
            created_time = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
            time_display = created_time.strftime('%H:%M')
        except:
            time_display = created_at.split(' ')[1][:5] if ' ' in created_at else created_at[:5]
        
        message_text += f"• {activity_name}: <b>{time_str}</b> (в {time_display})\n"
        total_minutes += duration
    
    total_hours = total_minutes // 60
    total_minutes_remain = total_minutes % 60
    
    message_text += f"\n⏱️ <b>Всего:</b> {total_hours}ч {total_minutes_remain}м"
    
    await message.answer(message_text, parse_mode=ParseMode.HTML)

# Команда /report - отчет с диаграммой
@dp.message_handler(commands=['report'])
async def cmd_report(message: types.Message):
    await message.answer(
        "📈 <b>Выберите дату для отчета:</b>\n\n"
        "Или введите дату в формате:\n"
        "<code>ДД.ММ.ГГГГ</code> (25.12.2023)\n"
        "<code>ДД-ММ-ГГГГ</code> (25-12-2023)\n"
        "<code>ДД/ММ/ГГГГ</code> (25/12/2023)",
        parse_mode=ParseMode.HTML,
        reply_markup=get_report_date_keyboard()
    )
    await TimeTracking.waiting_for_report_date.set()

# Обработчик выбора даты для отчета
@dp.message_handler(state=TimeTracking.waiting_for_report_date)
async def process_report_date(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    try:
        user_input = message.text.strip().lower()
        
        # Обработка специальных слов
        if user_input == 'вчера':
            report_date = date.today() - timedelta(days=1)
        elif user_input == 'позавчера':
            report_date = date.today() - timedelta(days=2)
        elif user_input == 'сегодня':
            report_date = date.today()
        else:
            # Пробуем разные форматы дат
            date_formats = [
                '%d.%m.%Y',  # 25.12.2023
                '%d-%m-%Y',  # 25-12-2023
                '%d/%m/%Y',  # 25/12/2023
                '%d.%m.%y',  # 25.12.23
                '%d-%m-%y',  # 25-12-23
                '%d/%m/%y',  # 25/12/23
            ]
            
            parsed_date = None
            for date_format in date_formats:
                try:
                    parsed_date = datetime.strptime(user_input, date_format).date()
                    break
                except ValueError:
                    continue
            
            if parsed_date is None:
                raise ValueError("Неверный формат даты")
            
            report_date = parsed_date
        
        # Проверяем, что дата не в будущем
        if report_date > date.today():
            await message.answer("❌ Дата не может быть в будущем!")
            return
        
        # Показываем ожидание
        wait_msg = await message.answer("⏳ <b>Генерирую отчет...</b>", parse_mode=ParseMode.HTML)
        
        # Получаем данные для отчета
        report_data = db.get_daily_report(user_id, report_date)
        
        await wait_msg.delete()  # Удаляем сообщение ожидания
        
        if not report_data or sum(report_data.values()) == 0:
            await message.answer(
                f"📭 <b>Нет данных за {report_date.strftime('%d.%m.%Y')}</b>\n\n"
                f"За этот день не было добавлено активностей.",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_keyboard()
            )
            await state.finish()
            return
        
        # Формируем текстовую часть отчета
        total_minutes = sum(report_data.values())
        total_hours = total_minutes // 60
        total_minutes_remain = total_minutes % 60
        
        activity_names = {
            "work": "💼 Работа",
            "sleep": "😴 Сон",
            "rest": "🎯 Отдых",
            "study": "📚 Учеба",
            "entertainment": "🎮 Развлечения"
        }
        
        text = f"📊 <b>Отчет за {report_date.strftime('%d.%m.%Y')}</b>\n\n"
        
        # Сортируем по убыванию времени
        sorted_activities = sorted(
            [(k, v) for k, v in report_data.items() if v > 0],
            key=lambda x: x[1],
            reverse=True
        )
        
        for activity_type, duration in sorted_activities:
            if duration > 0:
                hours = duration // 60
                minutes = duration % 60
                activity_name = activity_names.get(activity_type, activity_type)
                percentage = (duration / total_minutes) * 100 if total_minutes > 0 else 0
                
                if hours > 0:
                    time_str = f"{hours}ч {minutes}м"
                else:
                    time_str = f"{minutes}м"
                
                text += f"{activity_name}: <b>{time_str}</b> ({percentage:.1f}%)\n"
        
        text += f"\n⏱️ <b>Всего:</b> {total_hours}ч {total_minutes_remain}м"
        
        # Генерируем диаграмму
        try:
            chart_path = generate_daily_report(report_data, report_date, user_id)
            
            # Проверяем, что диаграмма создана
            if chart_path and os.path.exists(chart_path):
                # Отправляем диаграмму
                with open(chart_path, 'rb') as photo:
                    await bot.send_photo(
                        chat_id=message.chat.id,
                        photo=photo,
                        caption=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=get_main_keyboard()
                    )
                logger.info(f"Отчет отправлен с диаграммой: {chart_path}")
            else:
                # Отправляем только текстовый отчет
                await message.answer(
                    text + "\n\n⚠️ <i>Диаграмма не сгенерирована</i>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_main_keyboard()
                )
                logger.warning("Не удалось создать диаграмму, отправлен текстовый отчет")
                
        except Exception as e:
            logger.error(f"Ошибка генерации диаграммы: {e}")
            
            # Отправляем текстовый отчет
            await message.answer(
                text + f"\n\n⚠️ <i>Не удалось создать диаграмму: {str(e)}</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_keyboard()
            )
        
        await state.finish()
        
    except (ValueError, IndexError) as e:
        await message.answer(
            "❌ <b>Неверный формат даты!</b>\n\n"
            "Используйте один из форматов:\n"
            "• <code>25.12.2023</code>\n"
            "• <code>25-12-2023</code>\n"
            "• <code>25/12/2023</code>\n\n"
            "Или выберите вариант из кнопок",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка обработки отчета: {e}")
        await message.answer(
            "❌ <b>Произошла ошибка при обработке запроса</b>\n\n"
            "Попробуйте еще раз позже.",
            parse_mode=ParseMode.HTML
        )

# Команда /stats - статистика
@dp.message_handler(commands=['stats'])
async def cmd_stats(message: types.Message):
    user_id = message.from_user.id
    
    # Статистика за 30 дней
    end_date = date.today()
    start_date = end_date - timedelta(days=29)
    
    stats = db.get_user_statistics(user_id, start_date, end_date)
    
    if not stats:
        await message.answer(
            "📭 <b>Нет данных за последние 30 дней</b>\n\n"
            "Добавьте первую активность!",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Суммируем время по типам
    total_by_type = {
        'work': 0,
        'sleep': 0,
        'rest': 0,
        'study': 0,
        'entertainment': 0
    }
    
    total_minutes_all = 0
    
    for day_stats in stats:
        for activity_type in total_by_type.keys():
            if activity_type in day_stats:
                duration = day_stats[activity_type]
                total_by_type[activity_type] += duration
                total_minutes_all += duration
    
    # Формируем сообщение
    message_text = "📈 <b>Статистика за 30 дней</b>\n\n"
    
    activity_names = {
        "work": "💼 Работа",
        "sleep": "😴 Сон",
        "rest": "🎯 Отдых",
        "study": "📚 Учеба",
        "entertainment": "🎮 Развлечения"
    }
    
    # Сортируем по убыванию времени
    sorted_activities = sorted(
        [(k, v) for k, v in total_by_type.items() if v > 0],
        key=lambda x: x[1],
        reverse=True
    )
    
    for activity_type, total_duration in sorted_activities:
        hours = total_duration // 60
        minutes = total_duration % 60
        activity_name = activity_names.get(activity_type, activity_type)
        percentage = (total_duration / total_minutes_all) * 100 if total_minutes_all > 0 else 0
        
        if hours > 0:
            time_str = f"{hours}ч {minutes}м"
        else:
            time_str = f"{minutes}м"
        
        message_text += f"{activity_name}: <b>{time_str}</b> ({percentage:.1f}%)\n"
    
    total_hours = total_minutes_all // 60
    total_minutes = total_minutes_all % 60
    
    message_text += f"\n⏱️ <b>Всего за 30 дней:</b> {total_hours}ч {total_minutes}м"
    message_text += f"\n📅 <b>Период:</b> {start_date.strftime('%d.%m')} - {end_date.strftime('%d.%m.%Y')}"
    
    await message.answer(message_text, parse_mode=ParseMode.HTML)

# Команда /week - неделя
@dp.message_handler(commands=['week'])
async def cmd_week(message: types.Message):
    user_id = message.from_user.id
    
    # За последние 7 дней
    end_date = date.today()
    start_date = end_date - timedelta(days=6)
    
    stats = db.get_user_statistics(user_id, start_date, end_date)
    
    if not stats:
        await message.answer(
            "📭 <b>Нет данных за последнюю неделю</b>\n\n"
            "Добавьте первую активность!",
            parse_mode=ParseMode.HTML
        )
        return
    
    message_text = "📅 <b>Недельная статистика</b>\n\n"
    
    total_minutes_week = 0
    
    # Русские названия дней недели
    days_ru = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    
    # Создаем словарь для всех дней недели
    week_data = {}
    for i in range(7):
        current_date = start_date + timedelta(days=i)
        week_data[current_date] = 0
    
    # Заполняем данными
    for day_stats in stats:
        day_date = day_stats['date']
        day_total = sum([day_stats.get(k, 0) for k in ['work', 'sleep', 'rest', 'study', 'entertainment']])
        week_data[day_date] = day_total
        total_minutes_week += day_total
    
    # Выводим по дням
    for day_date, day_total in sorted(week_data.items()):
        hours = day_total // 60
        minutes = day_total % 60
        
        day_name = days_ru[day_date.weekday()]
        
        if day_total > 0:
            message_text += f"<b>{day_name} {day_date.strftime('%d.%m')}:</b> {hours}ч {minutes}м\n"
        else:
            message_text += f"<b>{day_name} {day_date.strftime('%d.%m')}:</b> нет данных\n"
    
    avg_minutes = total_minutes_week // 7
    avg_hours = avg_minutes // 60
    avg_minutes_remain = avg_minutes % 60
    
    total_hours_week = total_minutes_week // 60
    total_minutes_remain_week = total_minutes_week % 60
    
    message_text += f"\n📊 <b>Среднее в день:</b> {avg_hours}ч {avg_minutes_remain}м"
    message_text += f"\n⏱️ <b>Всего за неделю:</b> {total_hours_week}ч {total_minutes_remain_week}м"
    
    await message.answer(message_text, parse_mode=ParseMode.HTML)

# Обработчик кнопок главного меню
@dp.message_handler(lambda message: message.text in [
    "📊 Добавить активность", 
    "📈 Отчет за день", 
    "📅 Сегодня",
    "📊 Статистика",
    "📅 Неделя"
])
async def handle_main_buttons(message: types.Message):
    if message.text == "📊 Добавить активность":
        await cmd_add(message)
    elif message.text == "📈 Отчет за день":
        await cmd_report(message)
    elif message.text == "📅 Сегодня":
        await cmd_today(message)
    elif message.text == "📊 Статистика":
        await cmd_stats(message)
    elif message.text == "📅 Неделя":
        await cmd_week(message)

# Обработчик любых сообщений
@dp.message_handler()
async def handle_other_messages(message: types.Message):
    logger.info(f"Получено сообщение: {message.text}")
    await message.answer(
        "🤖 <b>Используйте кнопки или команды:</b>\n\n"
        "/start - Начало работы\n"
        "/add - Добавить активность\n"
        "/today - Сегодняшние активности\n"
        "/report - Отчет с диаграммой\n"
        "/stats - Статистика за 30 дней\n"
        "/week - Недельная статистика",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard()
    )

# Запуск бота
async def on_startup(dp):
    logger.info("✅ Бот запущен")
    # Проверяем подключение к БД
    try:
        db.connect()
        logger.info("✅ Подключение к БД установлено")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к БД: {e}")

async def on_shutdown(dp):
    logger.info("🛑 Бот остановлен")
    db.close()

if __name__ == '__main__':
    print("=" * 50)
    print("Time Tracker Bot")
    print("=" * 50)
    print("\nБот запускается...")
    print("Для остановки нажмите Ctrl+C")
    print("\nЛоги будут отображаться ниже:")
    print("-" * 50)
    
    executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown, skip_updates=True)
